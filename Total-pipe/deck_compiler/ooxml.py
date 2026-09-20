"""OPC paths and DrawingML color resolution shared by verification clients."""
import posixpath
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def target_part(source, target):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(f"Not an internal OPC target: {target}")
    target = unquote(parsed.path)
    if "\\" in target:
        raise ValueError("OPC targets use forward slashes")
    result = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                                 else posixpath.join(posixpath.dirname(source), target))
    if result in ("", ".", "..") or result.startswith("../"):
        raise ValueError("OPC target escapes package")
    return result


def relationships(z, source):
    relpath = posixpath.join(posixpath.dirname(source), "_rels", posixpath.basename(source) + ".rels")
    if relpath not in z.namelist():
        return {}
    return {r.get("Id"): {"type": r.get("Type", "").rsplit("/", 1)[-1],
                          "external": r.get("TargetMode") == "External",
                          "target": r.get("Target") if r.get("TargetMode") == "External"
                          else target_part(source, r.get("Target", ""))}
            for r in ET.fromstring(z.read(relpath))}


def slide_parts(z):
    root = ET.fromstring(z.read("ppt/presentation.xml"))
    rels = relationships(z, "ppt/presentation.xml")
    return [rels[s.get(f"{{{NS['r']}}}id")]["target"]
            for s in root.findall("p:sldIdLst/p:sldId", NS)]


def chain(z, part):
    seen = set()
    while part and part not in seen:
        seen.add(part)
        yield part, ET.fromstring(z.read(part))
        rels = relationships(z, part)
        part = next((r["target"] for r in rels.values()
                     if r["type"] in ("slideLayout", "slideMaster") and not r["external"]), None)


def theme_colors(z, part):
    for name, root in chain(z, part):
        for rel in relationships(z, name).values():
            if rel["type"] == "theme" and not rel["external"]:
                theme = ET.fromstring(z.read(rel["target"]))
                colors = {}
                scheme = theme.find(".//a:clrScheme", NS)
                if scheme is not None:
                    for entry in scheme:
                        c = next(iter(entry), None)
                        if c is not None:
                            colors[entry.tag.split("}")[-1]] = c.get("lastClr") or c.get("val")
                return colors
    return {}


def color_context(z, part):
    """Resolve the theme palette and effective color map for a slide chain."""
    nodes = list(chain(z, part))
    theme = theme_colors(z, part)
    mapping = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
    # Master defaults apply first; closer layout/slide overrides apply later.
    for _, node in reversed(nodes):
        cm = node.find("p:clrMap", NS)
        override = node.find("p:clrMapOvr/a:overrideClrMapping", NS)
        if cm is not None:
            mapping.update(cm.attrib)
        if override is not None:
            mapping.update(override.attrib)
    return theme, mapping


def color(node, theme=None, mapping=None):
    if node is None:
        return None
    theme = theme or {}
    mapping = mapping or {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
    tag = node.tag.split("}")[-1]
    if tag == "srgbClr":
        value = node.get("val")
    elif tag == "sysClr":
        value = node.get("lastClr")
    elif tag == "schemeClr":
        key = node.get("val")
        value = theme.get(mapping.get(key, key))
    else:
        return None
    if not value or len(value) != 6:
        return None
    rgb = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    for transform in node:
        kind = transform.tag.split("}")[-1]
        v = int(transform.get("val", "100000")) / 100000
        if kind == "alpha" and v < 1:
            return None  # requires compositing, never invent an opaque color
        if kind == "tint":
            rgb = [x + (1 - x) * v for x in rgb]
        elif kind == "shade":
            rgb = [x * v for x in rgb]
        elif kind in ("lumMod", "lumOff"):
            import colorsys
            h, l, s = colorsys.rgb_to_hls(*rgb)
            l = l * v if kind == "lumMod" else l + v
            rgb = list(colorsys.hls_to_rgb(h, min(1, max(0, l)), s))
        elif kind not in ("alpha",):
            return None
    return "#" + "".join(f"{round(min(1, max(0, x)) * 255):02X}" for x in rgb)


def fill(node, theme=None, mapping=None):
    """Only direct fills: a line's solidFill is not the shape's fill."""
    if node is None:
        return None
    solid = node.find("a:solidFill", NS)
    return color(next(iter(solid), None), theme, mapping) if solid is not None else None


def background(z, part):
    nodes = list(chain(z, part))
    theme, mapping = color_context(z, part)
    for name, node in nodes:
        bg = node.find("p:cSld/p:bg", NS)
        if bg is not None:
            resolved = fill(bg.find("p:bgPr", NS), theme, mapping)
            if resolved:
                return resolved, f"ooxml:{name}"
            return None, f"unresolved_fill:{name}"  # gradients/bgRef need native render
    return "#FFFFFF", "ooxml_default_background"
