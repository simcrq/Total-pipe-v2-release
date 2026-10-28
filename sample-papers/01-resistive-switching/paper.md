# Interfacial Control of Resistive Switching in Ti/Au–Si Memristive Junctions

> Synthetic sample paper for pipeline testing. The devices, numbers and citations are
> illustrative, not real experimental results.

## Abstract

We study resistive switching in Ti/Au–Si junctions fabricated on n-type Si(100). A thin
TiOx interlayer forms during contact deposition and controls trap-assisted conduction.
After electroforming at 2.8 ± 0.2 V, the junctions switch between a high-resistance state
of 1.2 × 10^5 Ω and a low-resistance state of 9.8 × 10^2 Ω. The ON/OFF ratio remains
above 10^2 for 10^4 s at 85 °C and survives 500 write–erase cycles with less than 12%
degradation. Temperature-dependent current–voltage measurements between 300 and 400 K
are consistent with Poole–Frenkel emission from interfacial traps, with an extracted
activation energy of 0.18 ± 0.02 eV. The results suggest that interface engineering,
rather than bulk doping, dominates the switching window in this simple two-terminal
structure.

## 1. Introduction

Two-terminal resistive switching devices are attractive for embedded memory because they
can be fabricated at low temperature and integrated in a back-end-of-line process.
Filamentary and interface-type switching are both reported in silicon-rich oxides, but the
relative contribution of the contact interface is often unclear. In this work we isolate
the contact interface by using a Ti/Au top contact on n-type Si without a deposited oxide.
The native oxide and the Ti-induced interlayer provide a thin switching layer.

The central question is whether the observed resistance change can be explained by
trap-assisted conduction at the TiOx/Si interface, and whether the switching window is
stable enough for a back-end memory element.

## 2. Methods

### 2.1 Device fabrication

Devices were fabricated on n-type Si(100) wafers with a resistivity of 1–10 Ω·cm. After a
standard solvent clean and a 60 s buffered HF dip, a 3.5 nm TiOx interlayer was formed by
Ti deposition and controlled oxidation. A 60 nm Ti adhesion layer and a 120 nm Au pad were
deposited by electron-beam evaporation through a shadow mask. The junction area was
100 µm × 100 µm. Cross-sectional TEM confirmed a continuous 3.5 nm TiOx layer between Si
and the Ti/Au contact. The switching layer is therefore an interfacial TiOx layer rather
than a deposited bulk oxide.

### 2.2 Electrical measurements

Current–voltage (I–V) curves were measured with a Keithley 2400 source meter in a probe
station. The bottom contact was grounded and the top contact was biased. Forming was
performed with a current compliance of 1 mA. Resistance states were read at 0.1 V to avoid
disturbing the state. Temperature-dependent measurements were performed from 300 to 400 K
on a heated stage in air. Endurance was measured for 500 write–erase cycles, and retention
was measured at 85 °C for 10^4 s.

## 3. Results

### 3.1 Forming and resistance states

The as-fabricated junctions were initially in a high-resistance state. Electroforming
occurred at 2.8 ± 0.2 V. After forming, the Ti/Au–Si junctions switch from a
high-resistance state of 1.2 × 10^5 Ω to a low-resistance state of 9.8 × 10^2 Ω. The
ON/OFF ratio is therefore about 1.2 × 10^2 at 0.1 V. The set voltage scales with the
square root of the electric field, as expected for trap-assisted conduction. Reset occurs
at a lower current compliance and does not require a reversal of the voltage polarity in
this geometry.

### 3.2 Retention and endurance

The ON/OFF ratio remained above 10^2 for 10^4 s at 85 °C under a 0.1 V read bias. Devices
endured 500 write–erase cycles without a decline larger than 12% in the ON/OFF ratio.
Cycle-to-cycle variation in the low-resistance state was 8% (coefficient of variation),
while the high-resistance state varied by 11%.

### 3.3 Conduction mechanism

The current–voltage curves between 300 and 400 K are consistent with Poole–Frenkel
emission from interfacial traps. A plot of ln(I/V) versus the square root of the electric
field is linear in the high-field region, and the slope is nearly temperature independent.
The extracted activation energy is 0.18 ± 0.02 eV, and the trap density is estimated as
2.4 × 10^18 cm^-3. These values are plausible for a TiOx interlayer with oxygen vacancies.

## 4. Discussion

The 3.5 nm TiOx interlayer formed during contact deposition is the most likely switching
region. Its thickness is consistent with trap-assisted transport rather than a metallic
filament bridging the entire junction. The weak temperature dependence of the high-field
slope supports a Poole–Frenkel process, although we cannot exclude a contribution from
Schottky emission at the TiOx/Si interface.

The switching window is adequate for a back-end memory element, but the absolute
resistance values depend on the contact geometry. The observed retention and endurance are
encouraging for a laboratory demonstration, but they do not yet establish product-level
reliability.

## 5. Limitations

The study is limited to n-type Si substrates and 100 µm junctions; CMOS integration and
high-frequency operation were not tested. The retention test used a single temperature and
did not include solder reflow. The conduction fit cannot uniquely separate Poole–Frenkel
emission from Schottky emission, and the trap density is an order-of-magnitude estimate.
No array-level disturb or sneak-path measurements were performed. The sample size was five
wafers, and the reported variation is therefore a process-level indication rather than a
statistical qualification.

## 6. Conclusion

Ti/Au–Si junctions with a 3.5 nm interfacial TiOx layer show forming-free read stability
after electroforming, a 10^2 ON/OFF ratio, 10^4 s retention at 85 °C and 500 cycles of
endurance. The electrical data are consistent with trap-assisted Poole–Frenkel conduction,
but a Schottky contribution cannot be excluded. Interface engineering is a promising route
for low-temperature silicon-compatible memory, subject to array-level validation.

## References

Synthetic references for the sample: [1] A. Author et al., "Interfacial oxides for
silicon-compatible memory," J. Synth. Devices 12, 101–110 (2024). [2] B. Author et al.,
"Trap-assisted conduction in thin oxides," Synth. Phys. Rev. 8, 221–230 (2025).
