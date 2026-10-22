"""Full-bleed slide backgrounds: measured, gated, and part of the compiled layout.

The test deck that motivated this shipped with a 1.8 MB decorative background stamped into the
slide master by a script that ran *after* QA. The report described bytes that were not the bytes
delivered, and nobody had measured what the picture did to the text on top of it.

A background is therefore an IR declaration, not a post-processing step: ``theme.background_image``
names a file next to the IR, the compiler places it underneath the slide's elements, and the
contrast and weight of the picture are measured before anything is written.
"""
from PIL import Image

# WCAG 2.1 relative luminance of an sRGB triplet.
def relative_luminance(rgb):
    channels = []
    for value in rgb[:3]:
        value = value / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(a, b):
    light, dark = max(a, b), min(a, b)
    return (light + 0.05) / (dark + 0.05)


def load(path):
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        return image.convert('RGB')


def statistics(image, samples=(36, 20)):
    """Luminance spread of a background, from a downscaled sample.

    A background that is uniform and far from the text colour is a design choice. A background
    whose dark patches sit near the text colour is a legibility defect that a textbox-over-picture
    never reveals, because nothing measures what is behind the text.
    """
    small = image.resize(samples)
    raw = small.tobytes()
    values = sorted(relative_luminance(raw[index:index+3]) for index in range(0, len(raw), 3))
    count = len(values)

    def percentile(fraction):
        return values[min(count - 1, max(0, int(round(fraction * (count - 1)))))]

    mean = sum(values) / count
    deviation = (sum((value - mean) ** 2 for value in values) / count) ** .5
    return {'dark': percentile(.05), 'light': percentile(.95), 'median': percentile(.5),
            'mean': mean, 'deviation': deviation, 'samples': count}


def review(path, foreground, size_bytes=0):
    """Contrast/busy/weight findings for one background image."""
    from .contracts import issue
    image = load(path)
    stats = statistics(image)
    text = relative_luminance(tuple(int(foreground.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)))
    worst = min(contrast_ratio(text, stats['dark']), contrast_ratio(text, stats['light']))
    findings = []
    detail = {key: round(value, 4) for key, value in stats.items() if key != 'samples'}
    detail.update({'foreground': foreground, 'worst_contrast': round(worst, 2),
                   'size_bytes': size_bytes})
    if worst < 3.0:
        findings.append(issue('BACKGROUND_CONTRAST', 'FAIL',
                              f'The background leaves only {worst:.1f}:1 contrast against the text '
                              'colour in its darkest or lightest area; text over it will not be '
                              'readable', detector='design-preflight', confidence='HIGH', **detail))
    elif worst < 4.5:
        findings.append(issue('BACKGROUND_CONTRAST', 'REVIEW',
                              f'Text over the background reaches {worst:.1f}:1 at its worst point; '
                              'confirm every caption and evidence id stays legible',
                              detector='design-preflight', confidence='MEDIUM', **detail))
    if stats['deviation'] > .075:
        findings.append(issue('BACKGROUND_BUSY', 'REVIEW',
                              f'The background carries strong light/dark variation '
                              f'(luminance sigma {stats["deviation"]:.2f}); text over a busy '
                              'picture needs checking in the render',
                              detector='design-preflight', confidence='MEDIUM', **detail))
    if size_bytes > 600_000:
        findings.append(issue('BACKGROUND_ASSET_LARGE', 'REVIEW',
                              f'The background is {size_bytes/1024/1024:.1f} MB; it travels in '
                              'every copy of the deck', detector='geometric-preflight',
                              confidence='HIGH', **detail))
    return stats, findings
