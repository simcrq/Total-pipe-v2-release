"""Define variables inline and present the key relation as an editable equation."""
from common import block_leaf, deck, page, region


def make_deck():
    blocks = [
        {'id': 'definition', 'component': 'body', 'inline_math': True,
         'text': r'For an ideal RC circuit, let $V_0$ be the initial capacitor voltage.'},
        {'id': 'decay', 'component': 'formula', 'anchor': 'definition',
         'text': r'\frac{V(t)}{V_0}=e^{-t/(RC)}'},
        {'id': 'symbols', 'component': 'body', 'inline_math': True,
         'text': r'$V(t)$ is the voltage at time $t$. $R$ is the resistance and $C$ is the capacitance.'},
        {'id': 'check', 'component': 'body', 'inline_math': True,
         'text': r'At $t=RC$, the remaining voltage is $V_0/e$, about 37% of its starting value.'},
    ]
    body = region('define-and-interpret', 'stack', [block_leaf(block['id']) for block in blocks],
                  gap='standard', align='center')
    slide = page('rc-discharge', 'An RC circuit discharges on the timescale RC',
                 'Model for a capacitor discharging through a resistor.', blocks, body,
                 evidence_refs=())
    return deck('equation-explainer', [slide])
