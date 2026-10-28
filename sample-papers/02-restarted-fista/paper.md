# Accelerated Sparse Recovery with Restarted FISTA

> Synthetic sample paper for pipeline testing. The algorithms, numbers and citations are
> illustrative, not real experimental results.

## Abstract

We evaluate a restarted variant of the fast iterative shrinkage-thresholding algorithm
(FISTA) for sparse recovery. On a benchmark with N = 512 and K = 50, restarted FISTA
reached a relative recovery error of 1.2 × 10^-3 after 200 iterations. A restart schedule
reduced the number of iterations needed to reach 10^-3 error by a factor of 1.8 compared
with standard FISTA, at the same per-iteration cost. The gain is largest when the
measurement matrix is well conditioned and decreases when the true support is highly
coherent. The method uses only matrix–vector products and proximal soft-thresholding, so
it remains suitable for large-scale problems.

## 1. Introduction

Sparse recovery aims to estimate a K-sparse vector from M linear measurements. The
LASSO formulation combines a least-squares data term with an ℓ1 penalty. Proximal gradient
methods are attractive because each iteration is cheap, but the objective can oscillate
near the solution. FISTA adds momentum and achieves O(1/k^2) objective convergence, yet
the momentum can be poorly matched to the local geometry. Restarting the momentum when the
objective increases is a simple remedy.

This paper asks whether a restart schedule improves the iteration count of FISTA on a
controlled sparse-recovery benchmark, and how the gain depends on support coherence.

## 2. Methods

### 2.1 Problem formulation

We solve the LASSO problem

    minimize  0.5 * ||A x - y||_2^2 + lambda * ||x||_1,

where A is an M × N Gaussian measurement matrix, y = A x_true + noise, and x_true is
K-sparse. The proximal step uses the soft-thresholding operator with a step size of 1/L,
where L is the Lipschitz constant of the gradient. The regularization weight is set to
lambda = 0.01 * ||A^T y||_inf.

### 2.2 Restart rule

The restart condition triggers when the objective increases relative to the previous
iterate. At a restart, the momentum coefficient is reset to zero while the current
iterate is kept. The gradient step and the proximal step are unchanged, so the restart
adds no matrix–vector products.

### 2.3 Benchmark

The measurement matrix was drawn from a Gaussian ensemble with unit-column normalization,
and measurements contained 30 dB additive white Gaussian noise. We used N = 512, K = 50,
and M = 256. The method was evaluated on 100 random trials, and the median error is
reported. We compared standard FISTA, FISTA with a fixed restart every 50 iterations, and
the adaptive restart rule. All methods used the same initialization and stopping criteria.

## 3. Results

### 3.1 Recovery accuracy and iteration count

Restarted FISTA reached a relative recovery error of 1.2 × 10^-3 after 200 iterations on
the N = 512, K = 50 benchmark. The restart schedule reduced the number of iterations to
reach 10^-3 error by a factor of 1.8 compared with standard FISTA. The fixed restart
schedule was slower than the adaptive rule in 71 of 100 trials.

### 3.2 Coherence ablation

The acceleration gain decreases when the true support is highly coherent. For a
coherence level of 0.2, the adaptive restart saved 42% of iterations; at a coherence level
of 0.8, the saving fell to 9%. In the high-coherence regime, the objective is non-monotone
for both methods, and the restart rule fires more often.

### 3.3 Runtime

The per-iteration runtime was 1.4 ms for both methods on a single CPU core. Because the
restart adds no matrix–vector products, the iteration savings translate directly into
runtime savings for this benchmark.

## 4. Discussion

The adaptive restart is most useful when the measurement matrix is well conditioned and
the support is not strongly coherent. In the coherent regime, the restart frequency
increases and the benefit shrinks. The result is consistent with the view that momentum
is helpful only when the local quadratic model is a good approximation.

The method does not change the asymptotic convergence rate; it changes the constant and
the transient behavior. This distinction matters for practical budgets of a few hundred
iterations, which is the regime studied here.

## 5. Limitations

Experiments use synthetic signals only; no hardware acquisition or real imaging data were
tested. The benchmark fixes the regularization weight and does not study warm starts. The
runtime comparison uses a single CPU implementation and does not include GPU effects. The
coherence ablation covers only Gaussian matrices, so structured dictionaries remain
untested. Finally, the restart rule requires an objective evaluation per iteration, which
may be non-negligible when the data term is expensive.

## 6. Conclusion

Restarted FISTA improves the iteration count of sparse recovery on a controlled benchmark,
with a 1.8× reduction to 10^-3 error and no additional matrix–vector products. The gain is
largest for well-conditioned supports and shrinks under high coherence. The method is a
practical drop-in for proximal gradient solvers when the objective is cheap to evaluate.

## References

Synthetic references for the sample: [1] C. Author et al., "Restart strategies for
accelerated proximal methods," Synth. Optim. Lett. 4, 55–66 (2024). [2] D. Author et al.,
"Sparse recovery phase transitions," Synth. Signal Process. 19, 301–315 (2025).
