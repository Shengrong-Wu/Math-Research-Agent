# Built-in Problem Answers

Reference solutions for selected hard built-in problems. These are provided
for evaluation purposes — to verify whether the agent's proofs are correct
and complete.

---

## RMM 2026 (17th Romanian Master of Mathematics)

### Problem 1 (`rmm2026_p1_triangle_subdivision`)

**Problem.** Given a positive integer n. Player A draws a triangle ABC
with area 1 on a blackboard. Then A performs the following operation n
times on the set T (initially T = {△ABC}): pick a triangle XYZ in T,
pick a point P strictly inside XYZ, and replace triangle XYZ in T with
the three triangles PXY, PYZ, PZX. After n operations, Player B selects
three triangles Δ₁, Δ₂, Δ₃ from T such that Δ₂ shares an edge with Δ₁
and Δ₃ shares a (different) edge with Δ₂. Find the largest constant C
such that, no matter how A plays, B can always guarantee that the sum of
the areas of Δ₁, Δ₂, Δ₃ is at least C.

**Answer.**

    C = 3/(2n + 1)

**Proof.**

Each operation replaces one leaf triangle with 3 new leaf triangles, so
after n operations the total number of leaf triangles is 1 + 2n = 2n + 1.

#### Upper bound: C ≤ 3/(2n + 1)

We construct a subdivision in which all 2n + 1 leaf triangles have equal
area 1/(2n + 1).

This is possible because when a triangle of area S is subdivided by an
interior point, the three sub-triangles can have any three positive areas
summing to S.

Concretely, proceed as follows:

- Step 1: split the original triangle into areas
  1/(2n+1), 1/(2n+1), (2n−1)/(2n+1).
- Step 2: split the triangle of area (2n−1)/(2n+1) into
  1/(2n+1), 1/(2n+1), (2n−3)/(2n+1).
- Continue in this fashion.
- Final step: split the triangle of area 3/(2n+1) into three
  triangles each of area 1/(2n+1).

This yields exactly 2n + 1 leaf triangles, each of area 1/(2n+1).
Any valid triple has area sum 3 · 1/(2n+1) = 3/(2n+1).

#### Lower bound: C ≥ 3/(2n + 1)

**Key Lemma.** The leaf triangles can always be arranged in a cyclic order
T₁, T₂, …, T₂ₙ₊₁ such that each Tᵢ shares an edge with Tᵢ₊₁
(indices mod 2n + 1).

*Proof of Lemma.* By induction on n.

- Base case n = 1: three sub-triangles formed by one interior point
  naturally form a 3-cycle.
- Inductive step: suppose the current leaf triangles form such a cycle.
  When a leaf triangle T is subdivided into T', T'', T''', replace T
  in the cycle with the three new triangles in their natural cyclic order
  around the new interior point. The two new triangles at the ends share
  edges with T's original neighbors; adjacent new triangles share edges
  with each other. So the cycle property is preserved. □

Now arrange the leaf triangles in cyclic order T₁, T₂, …, T₂ₙ₊₁.
For each i (indices mod 2n + 1), define

    sᵢ = [Tᵢ] + [Tᵢ₊₁] + [Tᵢ₊₂]

Each Tⱼ appears in exactly 3 of the sᵢ, so

    Σᵢ sᵢ = 3 · Σⱼ [Tⱼ] = 3

The average is 3/(2n + 1), so there exists some i with
sᵢ ≥ 3/(2n + 1).

The triple (Tᵢ, Tᵢ₊₁, Tᵢ₊₂) satisfies the problem's adjacency
requirement (the middle triangle shares an edge with each of the other two).
So B can always guarantee area sum at least 3/(2n + 1).

Combining both bounds: C = 3/(2n + 1). ∎

---

### Problem 2 (`rmm2026_p2_factorial_divisibility`)

**Problem.** Let p ≥ 11 be a prime. It is known that for all integers
1 ≤ a < b ≤ p − 3, we have p ∤ (b! − a!). Prove that 8 ∣ (p − 5).

**Proof.**

Let m = (p − 1)/2.

The hypothesis says that 1!, 2!, …, (p−3)! are pairwise distinct
modulo p. We must show p ≡ 5 (mod 8).

#### Step 1: p ≡ 1 (mod 4)

By Wilson's theorem, (p − 1)! ≡ −1 (mod p).

Split (p − 1)! into two halves:

    (p − 1)! = [∏(k=1 to m) k] · [∏(k=m+1 to p−1) k]

Since k ≡ −(p − k) (mod p):

    ∏(k=m+1 to p−1) k ≡ ∏(k=1 to m) (−k) = (−1)ᵐ · m!  (mod p)

So (m!)² · (−1)ᵐ ≡ −1 (mod p), i.e.,

    (m!)² ≡ (−1)ᵐ⁺¹ (mod p)

If p ≡ 3 (mod 4), then m is odd, so (m!)² ≡ 1 (mod p),
giving m! ≡ ±1 (mod p).

Since m ≤ p − 3 and 1! = 1, the distinctness hypothesis forces
m! ≢ 1, so m! ≡ −1 (mod p).

Then (m − 1)! = m!/m ≡ (−1)/m (mod p). Since
m = (p − 1)/2 ≡ −1/2 (mod p), we get
m⁻¹ ≡ −2 (mod p), so (m − 1)! ≡ 2 (mod p).

But 2! = 2 and m − 1 ≥ 4 (since p ≥ 11), contradicting
distinctness.

Therefore p ≡ 1 (mod 4), so m is even and
(m!)² ≡ −1 (mod p).

#### Step 2: Identify the two missing residue classes

Among the p − 1 nonzero residues mod p, the values 1!, 2!, …, (p−3)!
account for p − 3 distinct classes, so exactly two nonzero classes are missing.

We show these are −1 and −m!.

**Claim: −1 does not appear.**

By Wilson's theorem, for 1 ≤ a ≤ p − 3:

    a! · (p − a − 1)! ≡ (−1)ᵃ⁺¹ (mod p)

Suppose a! ≡ −1 (mod p) for some a ∈ [1, p − 3]. Then
(p − a − 1)! ≡ (−1)ᵃ (mod p).

- If a is even: (p − a − 1)! ≡ 1 ≡ 1!, contradicting distinctness.
- If a is odd: (p − a − 1)! ≡ −1 ≡ a!, so by distinctness
  p − a − 1 = a, giving a = m. But m is even, contradiction.

So −1 does not appear.

**Claim: −m! does not appear.**

Suppose a! ≡ −m! (mod p). Using (m!)² ≡ −1, so 1/m! ≡ −m! (mod p):

    (p − a − 1)! ≡ (−1)ᵃ⁺¹/a! ≡ (−1)ᵃ⁺¹/(−m!) ≡ (−1)ᵃ⁺¹ · m! (mod p)

- If a is odd: (p − a − 1)! ≡ m!, so p − a − 1 = m, giving a = m − 1.
  Then (m − 1)! ≡ −m! (mod p), so 1 ≡ −m (mod p), i.e.,
  m ≡ −1 (mod p). Impossible since 1 < m < p.
- If a is even: (p − a − 1)! ≡ −m! ≡ a!, so p − a − 1 = a, giving
  a = m. Then m! ≡ −m! (mod p), so 2 · m! ≡ 0 (mod p).
  Impossible.

So −m! also does not appear.

#### Step 3: Compute the product of all factorial residues

Let P = ∏(t=1 to p−3) t!.

Since 1!, …, (p−3)! cover all nonzero residues except −1 and −m!:

    P ≡ [∏(r ∈ (ℤ/pℤ)×) r] / [(−1)(−m!)] (mod p)

The product of all nonzero residues is −1 (Wilson), so
P ≡ −1/m! ≡ m! (mod p).

On the other hand, pair up factors using
k! · (p − k − 1)! ≡ (−1)ᵏ⁺¹ (mod p) for 2 ≤ k ≤ m − 1:

    P ≡ m! · ∏(k=2 to m−1) (−1)ᵏ⁺¹ = m! · (−1)ᴱ (mod p)

where

    E = Σ(k=2 to m−1) (k + 1) = Σ(j=3 to m) j = m(m + 1)/2 − 3

Comparing with P ≡ m! gives (−1)ᴱ = 1, so E is even.

Let m = 2t. Then

    E = 2t(2t + 1)/2 − 3 = t(2t + 1) − 3 ≡ t − 1 (mod 2)

So E is even iff t is odd, i.e., m ≡ 2 (mod 4).

Therefore:

    (p − 1)/2 ≡ 2 (mod 4)  ⟹  p − 1 ≡ 4 (mod 8)  ⟹  p ≡ 5 (mod 8)

Hence 8 ∣ (p − 5). ∎

---

### Problem 3 (`rmm2026_p3_finite_set_polynomial_system`)

**Problem.** Let S be a finite subset of ℝ³. Prove that there exist three
real-coefficient polynomials P(x,y,z), Q(x,y,z), and R(x,y,z) such that
a triple (a,b,c) ∈ ℝ³ belongs to S if and only if the system P(x,y,z) = a,
Q(x,y,z) = b, R(x,y,z) = c has no real solution.

Equivalently, we construct a polynomial map F: ℝ³ → ℝ³ whose image is
exactly ℝ³ \ S.

**Proof.**

#### Step 1: Reduce to points on the x-axis

Let S = {(a₁,b₁,c₁), …, (aₙ,bₙ,cₙ)}.

After a generic linear change of coordinates, we may assume aᵢ ≠ aⱼ
for i ≠ j.

By Lagrange interpolation, find univariate polynomials U, V with
U(aᵢ) = bᵢ and V(aᵢ) = cᵢ for all i.

The polynomial automorphism H(x,y,z) = (x, y + U(x), z + V(x)) has
polynomial inverse H⁻¹(x,y,z) = (x, y − U(x), z − V(x)), and
H(aᵢ, 0, 0) = (aᵢ, bᵢ, cᵢ).

So it suffices to construct a polynomial map G with
Im(G) = ℝ³ \ {(a₁,0,0), …, (aₙ,0,0)}, and then take F = H ∘ G.

#### Step 2: Construct G

Choose an integer r such that r ≠ a₁ − aᵢ for all 1 ≤ i ≤ N.

Define

    Π(x,y) = ∏(i=1 to N) (xy − r + a₁ − aᵢ)

Define the polynomial map

    G(x,y,z) = (xy − r + a₁,  x⁴·Π(x,y) + x²z² + y,  z)

#### Step 3: G does not hit the deleted points

Suppose G(x,y,z) = (aⱼ, 0, 0) for some j.

- Third coordinate: z = 0.
- First coordinate: xy − r + a₁ = aⱼ, i.e., xy − r + a₁ − aⱼ = 0.
  So Π(x,y) has a zero factor, hence Π(x,y) = 0.
- Second coordinate: x⁴·Π(x,y) + x²z² + y = 0 + 0 + y = 0,
  so y = 0.
- Back to the first coordinate: −r + a₁ = aⱼ, i.e., r = a₁ − aⱼ.
  This contradicts the choice of r.

So no deleted point is in Im(G).

#### Step 4: G hits everything else

Take any (u, v, w) ∉ {(a₁,0,0), …, (aₙ,0,0)}.

Set z = w.

**Case 1:** u = a₁ − r. Take x = 0, y = v, z = w. Then
G(0, v, w) = (a₁ − r, v, w) = (u, v, w). ✓

**Case 2:** u ≠ a₁ − r. From the first coordinate, y = (u − a₁ + r)/x.
Substituting into the second coordinate and multiplying by x:

    [∏(i=1 to N) (u − aᵢ)] · x⁵ + w² · x³ − v · x + (u − a₁ + r) = 0

This is an odd-degree polynomial in x with real coefficients:

- If u ≠ aᵢ for all i: degree 5 (odd).
- If u = aⱼ for some j: since (u,v,w) ∉ S', we have
  (v,w) ≠ (0,0), so the equation is still odd degree (≥ 1).

An odd-degree real polynomial always has a real root. The constant term
u − a₁ + r ≠ 0 (since we are in Case 2), so the root is nonzero.

Take such a nonzero root x₀, set y₀ = (u − a₁ + r)/x₀ and
z₀ = w. Then G(x₀, y₀, z₀) = (u, v, w). ✓

#### Step 5: Conclude

Im(G) = ℝ³ \ {(a₁,0,0), …, (aₙ,0,0)}.

Setting F = H ∘ G and writing F(x,y,z) = (P(x,y,z), Q(x,y,z), R(x,y,z))
gives the required polynomials. ∎

---

### Problem 4 (`rmm2026_p4_iterated_totient_prime_factors`)

**Problem.** For a positive integer m, let φ₀(m) = m, and for each
positive integer k, let φₖ(m) = φ(φₖ₋₁(m)). Given n ≥ 3, prove that

    φ₀(2ⁿ − 3) · φ₁(2ⁿ − 3) · φ₂(2ⁿ − 3) · … · φₙ(2ⁿ − 3)

has at most n distinct prime factors.

**Proof.**

Write N₀ = 2ⁿ − 3 and Nᵢ = φᵢ(2ⁿ − 3) for i ≥ 1.

#### Step 1: Build a forest of odd primes via parent-child relations

For each odd prime p dividing some Nⱼ, define its *level*
ℓ(p) = min{j ≥ 0 : p ∣ Nⱼ}.

If ℓ(p) = 0, call p a *root*.

If ℓ(p) ≥ 1, then p ∣ Nₗ₍ₚ₎ = φ(Nₗ₍ₚ₎₋₁) but p ∤ Nₗ₍ₚ₎₋₁. Using the formula

    φ(m) = ∏(qᵅ ‖ m) qᵅ⁻¹(q − 1)

since p ∤ Nₗ₍ₚ₎₋₁, the prime p cannot come from any qᵅ⁻¹ factor;
it must come from some (q − 1) factor. So there exists an odd prime
q ∣ Nₗ₍ₚ₎₋₁ with p ∣ (q − 1) and ℓ(q) < ℓ(p).

Assign q as the *parent* of p. This gives a forest whose roots are the
odd prime factors of N₀.

#### Step 2: Bound the size of each tree

For a root q, let T(q) denote the number of vertices in its tree.

**Claim:** T(q) ≤ log₂ q.

*Proof by induction.*

- If q has no children: T(q) = 1 ≤ log₂ q since q ≥ 3.
- If q has children p₁, …, pₛ: they are distinct odd primes
  dividing q − 1, so p₁ · p₂ · … · pₛ ≤ (q − 1)/2.

  By induction, T(pᵢ) ≤ log₂ pᵢ, so

      T(q) = 1 + Σᵢ T(pᵢ)
           ≤ 1 + Σᵢ log₂ pᵢ
           = 1 + log₂(p₁ · … · pₛ)
           ≤ 1 + log₂((q − 1)/2)
           = log₂(q − 1)
           < log₂ q     □

#### Step 3: Count all odd prime factors

Let q₁, …, qₜ be the distinct odd prime factors of N₀ = 2ⁿ − 3.
The total number of odd primes appearing across all N₀, …, Nₙ is at most

    Σᵢ T(qᵢ) ≤ Σᵢ log₂ qᵢ = log₂(q₁ · … · qₜ) ≤ log₂(N₀) = log₂(2ⁿ − 3) < n

So the number of distinct odd primes is at most n − 1.

#### Step 4: Account for the prime 2

N₀ = 2ⁿ − 3 is odd, so 2 is not a prime factor of N₀. Starting from
N₁ = φ(N₀), the prime 2 may appear, but it contributes at most one
additional distinct prime factor.

Therefore the total number of distinct prime factors of
N₀ · N₁ · … · Nₙ is at most (n − 1) + 1 = n. ∎

---

### Problem 6 (`rmm2026_p6_permutation_floor_inequality`)

**Problem.** Let k > 1 be an integer, and let S be the set of all
(k+1)-tuples X = (x₁, …, x_{k+1}) of integers with
1 ≤ x₁ < … < x_{k+1} ≤ k² + 1. For a permutation σ of {1, 2, …, k² + 1},
call an element X of S *σ-good* if σ(x₁), σ(x₂), …, σ(x_{k+1}) is
monotone. Prove that

    min₁≤ᵢ≤ₖ ⌊xᵢ/i⌋ + min₂≤ᵢ≤ₖ₊₁ ⌊(k² + 2 − xᵢ)/(k + 2 − i)⌋ ≥ k + 1

if and only if there exists a permutation σ such that X is the unique
σ-good tuple in S.

**Proof.**

Write A = min₁≤ᵢ≤ₖ ⌊xᵢ/i⌋ and B = min₂≤ᵢ≤ₖ₊₁ ⌊(k² + 2 − xᵢ)/(k + 2 − i)⌋.

#### Part 1: Necessity (⟸)

Assume there exists a permutation σ of {1, …, k² + 1} such that
X = (x₁, …, x_{k+1}) is the unique σ-good tuple in S.

**Step 1: Poset structure and WLOG reduction.**

Represent σ as a poset P = {(j, σ(j)) | 1 ≤ j ≤ k² + 1} under the
product order: (j, σ(j)) ≤ (j', σ(j')) iff j ≤ j' and σ(j) ≤ σ(j').
Then:

- A chain of length L in P corresponds to an increasing subsequence
  of length L.
- An antichain of length L corresponds to a decreasing subsequence
  of length L.

A σ-good tuple of length k + 1 is a chain or antichain of that length.
By the Erdős–Szekeres theorem, any sequence of k² + 1 distinct values
contains a monotone subsequence of length k + 1, so at least one σ-good
tuple exists. Since X is the unique such tuple, X must be either the
unique increasing subsequence of length k + 1 (with all decreasing
subsequences having length ≤ k) or the unique decreasing subsequence
of length k + 1 (with all increasing subsequences having length ≤ k).

*WLOG assume X is the unique increasing subsequence of length k + 1.*
(If X were the unique decreasing subsequence, replace σ by
σ'(j) = k² + 2 − σ(j). This swaps increasing and decreasing
subsequences without changing the indices X, so X becomes the unique
increasing subsequence under σ'. Since the floor condition depends only
on X and not on σ, the argument below applies.)

Under this assumption: the maximum chain length in P is k + 1, and
the maximum antichain size is at most k.

**Step 2: Dilworth partition.**

By Dilworth's theorem, P can be partitioned into w chains, where w is
the maximum antichain size. We claim w = k.

If w ≤ k − 1, each chain has length ≤ k + 1, so
|P| ≤ (k − 1)(k + 1) = k² − 1 < k² + 1, a contradiction.
So w ≥ k. Since the maximum antichain size is ≤ k (no decreasing
subsequence of length k + 1), we get w = k exactly.

Now partition P into k chains C₁, …, Cₖ. Each has length ≤ k + 1,
and their lengths sum to k² + 1. Since k · k = k² < k² + 1 ≤ k(k + 1),
exactly one chain has length k + 1 and the remaining k − 1 chains have
length k. The unique chain of length k + 1 must be X.

**Step 3: Grid bijection.**

For each y ∈ {1, …, k² + 1}, define:
- l(y) = length of the longest increasing subsequence ending at
  position y,
- d(y) = length of the longest decreasing subsequence ending at
  position y.

Since X is the unique increasing subsequence of length k + 1, we have
l(xᵢ) = i for 1 ≤ i ≤ k + 1. For any y ∉ X, l(y) ≤ k.

Define Aᵢ = {y : l(y) = i}. No two elements in Aᵢ can be in the same
increasing subsequence, so Aᵢ is an antichain (decreasing subsequence).
Thus |Aᵢ| ≤ k.

We have A_{k+1} = {x_{k+1}} (since l(y) = k + 1 only for y = x_{k+1}).
So Σᵢ₌₁ᵏ |Aᵢ| = k², and since |Aᵢ| ≤ k for each 1 ≤ i ≤ k, we must
have |Aᵢ| = k for all 1 ≤ i ≤ k.

Within each Aᵢ (an antichain of size k), ordering the elements as
y₁ < y₂ < … < yₖ with σ(y₁) > σ(y₂) > … > σ(yₖ):

- y₁, …, yⱼ is a decreasing subsequence of length j, so d(yⱼ) ≥ j.
- The decreasing subsequence ending at yⱼ can be extended by
  y_{j+1}, …, yₖ, giving length d(yⱼ) + (k − j) ≤ k, so d(yⱼ) ≤ j.

Therefore d(yⱼ) = j, and the d-values within Aᵢ are exactly {1, …, k}.

**Conclusion:** The map y ↦ (l(y), d(y)) is a bijection from
{1, …, k² + 1} \ {x_{k+1}} to the grid {1, …, k} × {1, …, k}, and
(l(x_{k+1}), d(x_{k+1})) = (k + 1, d(x_{k+1})).

**Step 4: Constancy of d(xᵢ).**

**Claim:** d(xᵢ) is the same for all 1 ≤ i ≤ k + 1.

*Proof.* We show d(x_{i−1}) = d(xᵢ) for each 2 ≤ i ≤ k + 1.
Write dᵢ = d(xᵢ). In the antichain A_{i−1}, there is a unique element
y with d(y) = dᵢ. We claim y = x_{i−1}.

Suppose for contradiction that y ≠ x_{i−1}. Then y ∉ X. We consider
all cases based on the relative position and σ-value of y and xᵢ.

**Case 1: y < xᵢ and σ(y) > σ(xᵢ).**
Then (y, σ(y)) and (xᵢ, σ(xᵢ)) are incomparable in P, so y extends the
longest decreasing subsequence ending at xᵢ: appending xᵢ after y gives
d(xᵢ) ≥ dᵢ + 1. Contradicts d(xᵢ) = dᵢ.

**Case 2: y < xᵢ and σ(y) < σ(xᵢ).**
Then y <_P xᵢ. Since l(y) = i − 1, there is an increasing subsequence
of length i − 1 ending at y. Extend it by xᵢ, x_{i+1}, …, x_{k+1} to
get length (i − 1) + (k + 2 − i) = k + 1. By uniqueness this must be X,
so y = x_{i−1}. Contradicts y ≠ x_{i−1}.

**Case 3: y > xᵢ and σ(y) > σ(xᵢ).**
Then y >_P xᵢ, so l(y) ≥ l(xᵢ) + 1 = i + 1. But l(y) = i − 1,
contradiction since i + 1 > i − 1.

**Case 4: y > xᵢ and σ(y) < σ(xᵢ).**
Then xᵢ < y and σ(xᵢ) > σ(y), so (xᵢ, y) form a decreasing pair.
Any decreasing subsequence ending at xᵢ (of length dᵢ) can be continued
to y, giving d(y) ≥ dᵢ + 1. But d(y) = dᵢ, contradiction.

All four cases lead to contradictions. Therefore y = x_{i−1}, giving
d(x_{i−1}) = d(y) = dᵢ = d(xᵢ).

By induction, d(x₁) = d(x₂) = … = d(x_{k+1}). Denote this common
value by A*. Since A* = d(x₁) and x₁ ∈ A₁, we have 1 ≤ A* ≤ k. □

**Step 5: Counting bounds on xᵢ.**

*Lower bound (1 ≤ i ≤ k): xᵢ ≥ i · A*.*

Consider the set Lᵢ = {y : l(y) ≤ i and d(y) ≤ A*}. For each
l ∈ {1, …, i}, the antichain Aₗ contains exactly A* elements with
d-value in {1, …, A*}. So |Lᵢ| = i · A*.

We claim every y ∈ Lᵢ satisfies y ≤ xᵢ. Suppose y > xᵢ:

- If σ(y) > σ(xᵢ): then y >_P xᵢ, so l(y) ≥ l(xᵢ) + 1 = i + 1,
  contradicting l(y) ≤ i.
- If σ(y) < σ(xᵢ): then (xᵢ, y) is a decreasing pair, giving
  d(y) ≥ A* + 1, contradicting d(y) ≤ A*.

So all i · A* elements of Lᵢ satisfy y ≤ xᵢ, giving xᵢ ≥ i · A*.

*Upper bound (2 ≤ i ≤ k + 1): xᵢ ≤ k² + 2 − (k + 2 − i)(k + 1 − A*).*

We count elements that must lie strictly after xᵢ.

**Set 1:** Elements y with l(y) ≥ i and d(y) ≥ A*, excluding xᵢ itself.
For each l ∈ {i, …, k}, the antichain Aₗ contributes (k − A* + 1)
elements. Additionally, x_{k+1} ∈ A_{k+1} has d(x_{k+1}) = A*.
Total minus xᵢ: (k − i + 1)(k − A* + 1).

We verify y > xᵢ: if y < xᵢ and σ(y) < σ(xᵢ), then l(xᵢ) ≥ l(y) + 1
≥ i + 1, contradiction. If y < xᵢ and σ(y) > σ(xᵢ), then
d(xᵢ) ≥ d(y) + 1 ≥ A* + 1, contradiction.

**Set 2:** Elements y ∈ A_{i−1} with d(y) ≥ A* + 1. There are (k − A*)
such elements. Similarly verified that y > xᵢ.

Sets 1 and 2 are disjoint (different l-values). Total elements > xᵢ:

    (k − i + 1)(k − A* + 1) + (k − A*) = (k + 1 − A*)(k + 2 − i) − 1

Since xᵢ + (elements > xᵢ) ≤ k² + 1:

    xᵢ ≤ k² + 2 − (k + 2 − i)(k + 1 − A*)

**Step 6: Conclude A + B ≥ k + 1.**

From the lower bound xᵢ ≥ i · A* (for 1 ≤ i ≤ k):
⌊xᵢ/i⌋ ≥ A*, so A ≥ A*.

From the upper bound (for 2 ≤ i ≤ k + 1):
k² + 2 − xᵢ ≥ (k + 2 − i)(k + 1 − A*), so
⌊(k² + 2 − xᵢ)/(k + 2 − i)⌋ ≥ k + 1 − A*, so B ≥ k + 1 − A*.

Adding: A + B ≥ A* + (k + 1 − A*) = k + 1.

This completes the necessity proof.

#### Part 2: Sufficiency (⟹)

Assume A + B ≥ k + 1. We construct a permutation σ such that X is the
unique σ-good tuple.

**Step 1: Corridor bounds.**

Set A* = A = min₁≤ᵢ≤ₖ ⌊xᵢ/i⌋. Then B ≥ k + 1 − A*. By definition:
for all 1 ≤ i ≤ k, xᵢ ≥ i · A*; for all 2 ≤ i ≤ k + 1,
xᵢ ≤ k² + 2 − (k + 2 − i)(k + 1 − A*). In summary:

    i · A* ≤ xᵢ ≤ k² + 2 − (k + 2 − i)(k + 1 − A*)   for all relevant i

Note 1 ≤ A* ≤ k.

**Step 2: Grid and bucket setup.**

Define the target grid:

    G = {(l, d) : 1 ≤ l ≤ k, 1 ≤ d ≤ k} ∪ {(k + 1, A*)}

so |G| = k² + 1. Equip G with the product partial order ⪯_G.

We construct a bijection f: {1, …, k² + 1} → G such that:

(a) f(xᵢ) = (i, A*) for all 1 ≤ i ≤ k + 1,
(b) j < j' implies f(j) precedes f(j') in a linear extension of ⪯_G.

Set f(xᵢ) = (i, A*). The remaining grid points split into:

- S⁻ = {(l, d) : 1 ≤ l ≤ k, 1 ≤ d ≤ A* − 1}, with |S⁻| = k(A* − 1).
- S⁺ = {(l, d) : 1 ≤ l ≤ k, A* + 1 ≤ d ≤ k}, with |S⁺| = k(k − A*).

So |S⁻| + |S⁺| = k(k − 1) = k² − k, matching the k² − k non-X integers.

Define buckets B₀, B₁, …, B_{k+1} corresponding to the gaps between
consecutive elements of X (with sentinels x₀ = 0, x_{k+2} = k² + 2):
bucket Bⱼ consists of the integers in the open interval (xⱼ, x_{j+1}),
with capacity sⱼ = x_{j+1} − xⱼ − 1.

Assignment constraints:
- **S⁻ constraint:** A point (l, d) ∈ S⁻ has d < A*, so it must be
  assigned an integer < xₗ, i.e., bucket Bⱼ with j ≤ l − 1.
- **S⁺ refined constraint:** A point (l, d) ∈ S⁺ has d > A*, so it
  must get an integer > xₗ. For uniqueness (Step 7 below), we impose
  the *stronger* requirement j ≥ l + 1, i.e., integer > x_{l+1}.

**Step 3: Feasibility of the bucket assignment.**

We must show a valid assignment exists. This is a transportation problem
with interval constraints. By the max-flow min-cut theorem, it suffices
to check sets of the form T = [0, i − 1] ∪ [j, k + 1] for
1 ≤ i ≤ j ≤ k + 1.

*Forced supply:*
- S⁻ sources at level l ≤ i: total i(A* − 1).
- S⁺ sources at level l ≥ j − 1: total (k − j + 2)(k − A*).

*Capacity:*

    cap(T) = xᵢ − xⱼ + k² − k + j − i

*Verification:* We need

    xᵢ − xⱼ + k² − k + j − i ≥ i(A* − 1) + (k − j + 2)(k − A*)

Rearranging:

    (xᵢ − i · A*) + ((k² + 2 − xⱼ) − (k + 2 − j)(k + 1 − A*)) ≥ 0

Both terms are ≥ 0 by the corridor bounds. □

**Step 4: Constructing the bijection f.**

Order S⁻ elements lexicographically: (l, d) <_lex (l', d') if l < l',
or l = l' and d < d'. This is a linear extension of ⪯_G on S⁻.
Assign S⁻ elements to buckets in this order. Similarly for S⁺.

Within each bucket, S⁻ elements have l ≥ j + 1 and S⁺ elements have
l ≤ j − 1 (where j is the bucket index), so l(S⁻) > l(S⁺). Since
d(S⁻) < A* < d(S⁺), they are incomparable in ⪯_G. Placing S⁻ before
S⁺ within each bucket is consistent.

The final bijection: B₀, f(x₁), B₁, f(x₂), …, f(x_{k+1}), B_{k+1}.
By construction, this is a linear extension of ⪯_G.

**Step 5: Define σ.**

Define (l, d) ≺_σ (l', d') iff (−d, l) <_lex (−d', l'), i.e., higher
depth gets smaller σ-value; within the same depth, lower level gets
smaller value. Set σ(j) = rank of f(j) under ≺_σ.

**Step 6: X is σ-good.**

For each xᵢ ∈ X, f(xᵢ) = (i, A*). For consecutive x_i, x_{i+1}: depths
are equal (A*) and levels satisfy i < i + 1, so (−A*, i) <_lex (−A*, i+1),
giving σ(xᵢ) < σ(x_{i+1}). Thus σ(x₁) < σ(x₂) < … < σ(x_{k+1}): X is
σ-good (increasing).

**Step 7: X is the unique increasing subsequence of length k + 1.**

Let Y = (y₁, …, y_{k+1}) be any increasing subsequence of length k + 1.
Write f(yₐ) = (lₐ, dₐ).

*Claim: lₐ < l_b for all a < b (levels strictly increasing).*

From σ(yₐ) < σ(y_b): (−dₐ, lₐ) <_lex (−d_b, l_b), so dₐ ≥ d_b.
If lₐ ≥ l_b, then f(y_b) ⪯_G f(yₐ), and since f is a linear extension,
y_b ≤ yₐ, contradicting yₐ < y_b.

Since l₁ < l₂ < … < l_{k+1} are integers in {1, …, k + 1}, we have
lₐ = a for all a.

The only element at level k + 1 is (k + 1, A*) = f(x_{k+1}), so
y_{k+1} = x_{k+1}. The depth sequence is non-increasing (dₐ ≥ d_b for
a < b) with d_{k+1} = A*, so dₐ ≥ A* for all a. Each yₐ is either xₐ
(with dₐ = A*) or an S⁺ element at level a (with dₐ > A*).

*Uniqueness by downward induction.*

Base: y_{k+1} = x_{k+1}.

Inductive step: assume yₘ = xₘ for all m > a. Then yₐ < y_{a+1} = x_{a+1}.
If yₐ ≠ xₐ, then yₐ ∈ S⁺ at level a. By the refined bucket constraint,
every S⁺ element at level a is assigned to bucket Bₘ with m ≥ a + 1,
meaning yₐ > x_{a+1}. But yₐ < x_{a+1}, contradiction.

Therefore yₐ = xₐ, and by induction Y = X. □

**Step 8: No decreasing subsequence of length k + 1.**

Let Y = (y₁, …, yₘ) be a decreasing subsequence. From
σ(yₐ) > σ(y_b) for a < b: (−dₐ, lₐ) >_lex (−d_b, l_b), so dₐ < d_b
(strictly — the equal case leads to l_b < lₐ, giving f(y_b) ⪯_G f(yₐ)
and y_b ≤ yₐ, contradiction).

The depths d₁ < d₂ < … < dₘ are strictly increasing in {1, …, k}, so
m ≤ k. No decreasing subsequence of length k + 1 exists. □

**Step 9: Conclusion.**

Steps 6–8 show: σ makes X σ-good (Step 6); X is the unique increasing
subsequence of length k + 1 (Step 7); no decreasing subsequence of
length k + 1 exists (Step 8). Since any σ-good tuple must be a monotone
subsequence of length k + 1, and the only such is X, we conclude X is
the unique σ-good tuple.

Combining Parts 1 and 2: A + B ≥ k + 1 if and only if there exists σ
making X the unique σ-good tuple. ∎
