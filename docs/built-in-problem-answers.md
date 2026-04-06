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
