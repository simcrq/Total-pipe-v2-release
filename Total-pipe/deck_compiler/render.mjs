/** Artifact-tool backend. Receives compiled geometry, never semantic input. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const modulePath = process.env.ARTIFACT_TOOL_MODULE;
const { Presentation, PresentationFile } = await import(modulePath ? pathToFileURL(modulePath).href : '@oai/artifact-tool');
const [layoutPath, outputPath] = process.argv.slice(2);
if (!layoutPath || !outputPath) throw new Error('render.mjs layout.json candidate.pptx');
const layout = JSON.parse(await fs.readFile(layoutPath, 'utf8'));
const deck = Presentation.create({slideSize: {width: layout.slide_size[0], height: layout.slide_size[1]}});
for (const source of layout.slides) {
  const slide = deck.slides.add();
  slide.background.fill = source.background;
  slide.speakerNotes.textFrame.setText(source.notes);
  for (const el of source.elements) {
    const [left, top, width, height] = el.bbox;
    const position = {left, top, width, height};
    if (el.kind === 'image') {
      const asset = layout.assets[el.asset_id];
      slide.images.add({blob: new Uint8Array(await fs.readFile(asset.path)), contentType: asset.content_type,
        alt: el.id + ': ' + el.alt, position, fit: 'contain'});
    } else if (el.kind === 'shape') {
      slide.shapes.add({name: el.id, geometry: el.geometry ?? 'rect', position,
        fill: el.fill, line: {fill: el.line, width: el.line_width ?? 1}});
    } else {
      const c = el.contract;
      const shape = slide.shapes.add({name: el.id, geometry: 'textbox', position,
        fill: 'none', line: {fill: 'none', width: 0}});
      shape.text = el.text;
      shape.text.style = {typeface: c.font_family, fontSize: c.font_size,
        bold: c.font_weight >= 700, color: el.color, lineSpacing: c.line_height,
        wrap: c.wrap ? 'square' : 'none', autoFit: c.autofit,
        insets: c.inset, verticalAlignment: c.vertical_anchor};
    }
  }
}
await fs.mkdir(path.dirname(outputPath), {recursive: true});
await (await PresentationFile.exportPptx(deck)).save(outputPath);
