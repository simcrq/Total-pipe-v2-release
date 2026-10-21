# Demo deck

A six-page deck that the pipeline lays out by itself. It is also the regression page for the
`packer` provider: every number quoted in the text and in the chart is written by
`tools/demo_measurements.py`, so prose, picture and compiler cannot drift apart.

Rebuild everything:

```bash
python tools/demo_measurements.py          # measurements.json
python examples/demo_deck/make_figures.py  # figures/*.png
python -m deck_compiler build --ir examples/demo_deck/demo.deck_ir.json --out builds/demo_deck
python -m deck_compiler review-officecli   # page images, if you want to look at them
```

`demo.deck_ir.json` contains no geometry: only text, figures and the archetype. The body layout
comes from the layout provider (`packer` by default); `--layout-provider compiler` lays the same
pages out with the compiler's own templates.
