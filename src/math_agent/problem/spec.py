"""ProblemSpec dataclass and built-in problem/suite registry."""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProblemSpec:
    """Immutable specification for a single math problem."""

    problem_id: str
    question: str
    domain: str
    evaluation_mode: str = "theorem"
    difficulty_level: int = 1
    difficulty_label: str = "toy"
    reference_claims: list[str] = field(default_factory=list)
    required_statement_terms: list[str] = field(default_factory=list)
    good_roadmap_terms: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in problems  (47 unique entries, L1-L6)
# ---------------------------------------------------------------------------

_PROBLEMS: dict[str, ProblemSpec] = {}


def _register(spec: ProblemSpec) -> None:
    _PROBLEMS[spec.problem_id] = spec


# --- difficulty 1 (toy) ---------------------------------------------------

_register(ProblemSpec(
    problem_id="sum_first_n_odds",
    question=(
        "Find and prove a closed-form formula for the sum of the first n odd "
        "numbers, i.e. compute 1 + 3 + 5 + ... + (2n-1) and prove the result "
        "by mathematical induction."
    ),
    domain="elementary_number_theory",
    difficulty_level=1,
    difficulty_label="toy",
))

_register(ProblemSpec(
    problem_id="square_expansion_commutative_ring",
    question=(
        "Let R be a commutative ring and let x, y in R. "
        "Prove that (x + y)^2 = x^2 + 2xy + y^2."
    ),
    domain="commutative_algebra",
    difficulty_level=1,
    difficulty_label="toy",
))

_register(ProblemSpec(
    problem_id="difference_of_squares_commutative_ring",
    question=(
        "Let R be a commutative ring and let x, y in R. "
        "Prove that (x + y)(x - y) = x^2 - y^2."
    ),
    domain="commutative_algebra",
    difficulty_level=1,
    difficulty_label="toy",
))

_register(ProblemSpec(
    problem_id="difference_of_cubes_commutative_ring",
    question=(
        "Let R be a commutative ring and let x, y in R. "
        "Prove that x^3 - y^3 = (x - y)(x^2 + xy + y^2)."
    ),
    domain="commutative_algebra",
    difficulty_level=1,
    difficulty_label="toy",
))

# --- difficulty 2 ----------------------------------------------------------

_register(ProblemSpec(
    problem_id="harmonic_sum_not_integer",
    question=(
        "Prove that the harmonic sum H_n = 1 + 1/2 + 1/3 + ... + 1/n "
        "is not an integer for any n >= 2."
    ),
    domain="number_theory",
    difficulty_level=2,
    difficulty_label="toy",
))

_register(ProblemSpec(
    problem_id="real_projective_space_orientability",
    question=(
        "Prove that the real projective space RP^n is orientable "
        "if and only if n is odd."
    ),
    domain="topology",
    difficulty_level=2,
    difficulty_label="toy",
))

# --- difficulty 3 (phd_qe) ------------------------------------------------

_register(ProblemSpec(
    problem_id="pid_prime_implies_maximal",
    question="Prove that every nonzero prime ideal in a PID is maximal.",
    domain="commutative_algebra",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

_register(ProblemSpec(
    problem_id="radical_intersection_product",
    question=(
        "Prove that rad(I \u2229 J) = rad(IJ) = rad(I) \u2229 rad(J)."
    ),
    domain="commutative_algebra",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

_register(ProblemSpec(
    problem_id="localization_preserves_intersection",
    question=(
        "If S is multiplicatively closed, prove "
        "S^{-1}(I \u2229 J) = S^{-1}I \u2229 S^{-1}J."
    ),
    domain="commutative_algebra",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

_register(ProblemSpec(
    problem_id="nakayama_zero_module_local",
    question=(
        "If (R, m) is a local ring, M is finitely generated, "
        "and M = mM, prove M = 0."
    ),
    domain="commutative_algebra",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

_register(ProblemSpec(
    problem_id="compact_to_hausdorff_homeomorphism",
    question=(
        "Prove that a continuous bijection from a compact space "
        "to a Hausdorff space is a homeomorphism."
    ),
    domain="topology",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

_register(ProblemSpec(
    problem_id="nonabelian_group_conjugacy_class_ratio",
    question=(
        "Let G be a non-abelian group. Prove that the index "
        "[G : Z(G)] cannot equal any prime p."
    ),
    domain="algebra",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

_register(ProblemSpec(
    problem_id="two_dim_rep_eigenvalue_one_direct_sum",
    question=(
        "Let V be a 2-dimensional complex representation of a finite "
        "group G such that every element of G acts on V with 1 as an "
        "eigenvalue. Prove that V contains a trivial subrepresentation."
    ),
    domain="algebra",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

_register(ProblemSpec(
    problem_id="five_lemma_abelian_groups",
    question="Prove the five lemma for abelian groups.",
    domain="algebra",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

_register(ProblemSpec(
    problem_id="group_order_150_not_simple",
    question="Prove that no group of order 150 is simple.",
    domain="algebra",
    difficulty_level=3,
    difficulty_label="phd_qe",
))

# --- difficulty 4 (beyond_qe / olympiad_longproof) -------------------------

_register(ProblemSpec(
    problem_id="hilbert_basis_theorem",
    question=(
        "Prove the Hilbert Basis Theorem: if R is a Noetherian ring, then "
        "the polynomial ring R[x] is also Noetherian. That is, every ideal "
        "of R[x] is finitely generated."
    ),
    domain="commutative_algebra",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="pid_torsion_free_module_free",
    question=(
        "Prove that every finitely generated torsion-free module "
        "over a PID is free."
    ),
    domain="algebra",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="chinese_remainder_comaximal",
    question=(
        "If I and J are comaximal ideals, prove "
        "R/(I \u2229 J) \u2245 R/I \u00d7 R/J."
    ),
    domain="commutative_algebra",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="finite_dimensional_normed_space_complete",
    question=(
        "Prove that every finite-dimensional normed vector space "
        "is complete."
    ),
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="projective_module_local_ring_free",
    question=(
        "Prove that every finitely generated projective module "
        "over a local ring is free."
    ),
    domain="commutative_algebra",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="lebesgue_dominated_convergence",
    question=(
        "Prove the Lebesgue Dominated Convergence Theorem: Let (f_n) be a "
        "sequence of measurable functions on a measure space (X, M, mu) that "
        "converge pointwise a.e. to a function f. If there exists an integrable "
        "function g such that |f_n(x)| <= g(x) a.e. for all n, then f is "
        "integrable and the integral of f_n converges to the integral of f."
    ),
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="open_mapping_theorem_banach",
    question=(
        "Prove the Open Mapping Theorem: Let X and Y be Banach spaces and "
        "let T: X -> Y be a bounded linear operator that is surjective. "
        "Then T is an open map, i.e. T maps open subsets of X to open "
        "subsets of Y."
    ),
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="uniform_boundedness_principle",
    question=(
        "Prove the Uniform Boundedness Principle (Banach-Steinhaus Theorem): "
        "Let X be a Banach space and Y a normed vector space. If {T_alpha} is "
        "a family of bounded linear operators from X to Y such that for every "
        "x in X, sup_alpha ||T_alpha(x)|| < infinity, then "
        "sup_alpha ||T_alpha|| < infinity."
    ),
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="hahn_banach_extension",
    question=(
        "Prove the Hahn-Banach Extension Theorem: Let X be a real vector space, "
        "p: X -> R a sublinear functional, M a subspace of X, and f: M -> R a "
        "linear functional with f(x) <= p(x) for all x in M. Then there exists "
        "a linear functional F: X -> R extending f such that F(x) <= p(x) for "
        "all x in X."
    ),
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="galois_group_x8_minus_5",
    question=(
        "Compute the Galois group Gal(K/Q) where K is the splitting field of "
        "x^8 - 5 over Q. Determine its order, describe it as a semidirect "
        "product, and identify all intermediate subfields."
    ),
    domain="algebra",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="sl2r_symmetric_power_irreducible",
    question=(
        "Prove that Sym^n(V) of the standard rep of SL_2(R) "
        "is irreducible."
    ),
    domain="algebra",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="pid_submodule_free_rank",
    question=(
        "Prove that every submodule of a free module of rank n "
        "over a PID is free with rank at most n."
    ),
    domain="algebra",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="imo2024_a1_floor_sum_divisibility",
    question=(
        "IMO 2024 Shortlist A1: Determine all real numbers alpha such that "
        "floor(alpha) + floor(2*alpha) + ... + floor(n*alpha) is divisible "
        "by n for every positive integer n."
    ),
    domain="algebra",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

_register(ProblemSpec(
    problem_id="imo2024_a2_weighted_square_minimum",
    question=(
        "IMO 2024 Shortlist A2: Let x_0, x_1, ..., x_n be nonnegative "
        "integers with x_0 + x_1 + ... + x_n = n. Determine the minimum "
        "possible value of S = 2^0 * x_0^2 + 2^1 * x_1^2 + ... + 2^n * x_n^2."
    ),
    domain="algebra",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

_register(ProblemSpec(
    problem_id="imo2024_n1_divisor_plus_one",
    question=(
        "IMO 2024 Shortlist N1: Find all positive integers n such that for "
        "every positive divisor d of n, either d + 1 divides n or d + 1 is prime."
    ),
    domain="number_theory",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

_register(ProblemSpec(
    problem_id="imo2024_n2_divisibility_sets",
    question=(
        "IMO 2024 Shortlist N2: Determine all finite nonempty sets S of "
        "positive integers such that for every a, b in S there exists c in S "
        "with a dividing b + 2c."
    ),
    domain="number_theory",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

_register(ProblemSpec(
    problem_id="imo2024_n3_integral_means_sequence",
    question=(
        "IMO 2024 Shortlist N3: Determine all sequences a_1, a_2, ... of "
        "positive integers such that for every m <= n, both the arithmetic "
        "mean and geometric mean of a_m, a_{m+1}, ..., a_n are integers."
    ),
    domain="number_theory",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

# --- difficulty 5 (research) ----------------------------------------------

_register(ProblemSpec(
    problem_id="weak_nullstellensatz",
    question=(
        "Prove the Weak Nullstellensatz: Let k be an algebraically closed field "
        "and let I be a proper ideal of k[x_1, ..., x_n]. Then V(I), the set of "
        "common zeros of I in k^n, is nonempty. Equivalently, if f_1, ..., f_m "
        "in k[x_1, ..., x_n] have no common zero in k^n, then 1 lies in the "
        "ideal (f_1, ..., f_m)."
    ),
    domain="algebraic_geometry",
    difficulty_level=5,
    difficulty_label="research",
))

_register(ProblemSpec(
    problem_id="krull_intersection_theorem_local",
    question=(
        "Prove the Krull Intersection Theorem: Let (R, m) be a Noetherian "
        "local ring and let M be a finitely generated R-module. Then the "
        "intersection of m^n * M over all n >= 0 is zero. That is, "
        "the m-adic topology on M is Hausdorff."
    ),
    domain="commutative_algebra",
    difficulty_level=5,
    difficulty_label="research",
))

_register(ProblemSpec(
    problem_id="lasker_noether_primary_decomposition",
    question=(
        "Prove the Lasker-Noether Primary Decomposition Theorem: Every ideal "
        "in a Noetherian ring can be written as a finite intersection of "
        "primary ideals. Prove both existence and the uniqueness of the "
        "associated primes (first uniqueness theorem)."
    ),
    domain="commutative_algebra",
    difficulty_level=5,
    difficulty_label="research",
))

_register(ProblemSpec(
    problem_id="krein_milman_extreme_points",
    question=(
        "Prove the Krein-Milman Theorem: Every compact convex subset of a "
        "locally convex Hausdorff topological vector space is the closed "
        "convex hull of its extreme points."
    ),
    domain="analysis",
    difficulty_level=5,
    difficulty_label="research",
))

_register(ProblemSpec(
    problem_id="polynomial_roots_mod_p_not_rational",
    question=(
        "Let f(x) in Z[x] be a monic irreducible polynomial of degree n >= 2. "
        "Prove that the set of primes p for which f(x) has a root modulo p has "
        "natural density 1/n if and only if the Galois group of f is cyclic. "
        "(This is a consequence of the Chebotarev Density Theorem.)"
    ),
    domain="algebra",
    difficulty_level=5,
    difficulty_label="research",
))

# --- difficulty 5 (competition_hard / RMM 2026 Day 1 P1-3, Day 2 P4) -----

_register(ProblemSpec(
    problem_id="rmm2026_p1_triangle_subdivision",
    question=(
        "RMM 2026 Problem 1: Given a positive integer n. Player A draws a "
        "triangle ABC with area 1 on a blackboard. Then A performs the following "
        "operation n times on the set T (initially T = {triangle ABC}): pick a "
        "triangle XYZ in T, pick a point P strictly inside XYZ, and replace "
        "triangle XYZ in T with the three triangles PXY, PYZ, PZX. After n "
        "operations, Player B selects three triangles D1, D2, D3 from T such "
        "that D2 shares an edge with D1 and D3 shares a (different) edge with D2. "
        "Find the largest constant C such that, no matter how A plays, B can "
        "always guarantee that the sum of the areas of D1, D2, D3 is at least C."
    ),
    domain="combinatorics",
    difficulty_level=5,
    difficulty_label="competition_hard",
))

_register(ProblemSpec(
    problem_id="rmm2026_p2_factorial_divisibility",
    question=(
        "RMM 2026 Problem 2: Let p >= 11 be a prime. It is known that for all "
        "integers 1 <= a < b <= p - 3, we have p does not divide b! - a!. "
        "Prove that 8 divides p - 5."
    ),
    domain="number_theory",
    difficulty_level=5,
    difficulty_label="competition_hard",
))

_register(ProblemSpec(
    problem_id="rmm2026_p3_finite_set_polynomial_system",
    question=(
        "RMM 2026 Problem 3: Let S be a finite subset of R^3. Prove that there "
        "exist three real-coefficient polynomials P(x,y,z), Q(x,y,z), and "
        "R(x,y,z) such that a triple (a,b,c) in R^3 belongs to S if and only "
        "if the system P(x,y,z) = a, Q(x,y,z) = b, R(x,y,z) = c has no real "
        "solution."
    ),
    domain="algebraic_geometry",
    difficulty_level=5,
    difficulty_label="competition_hard",
))

_register(ProblemSpec(
    problem_id="rmm2026_p4_iterated_totient_prime_factors",
    question=(
        "RMM 2026 Problem 4: For a positive integer m, let phi_0(m) = m, and "
        "for each positive integer k, let phi_k(m) = phi(phi_{k-1}(m)) where "
        "phi is the Euler totient function. Given n >= 3, prove that the product "
        "phi_0(2^n - 3) * phi_1(2^n - 3) * phi_2(2^n - 3) * ... * phi_n(2^n - 3) "
        "has at most n distinct prime factors."
    ),
    domain="number_theory",
    difficulty_level=5,
    difficulty_label="competition_hard",
))

# --- difficulty 6 (competition_extreme / research_extreme) -----------------

_register(ProblemSpec(
    problem_id="rmm2026_p5_parallelogram_circumcircle",
    question=(
        "RMM 2026 Problem 5: In triangle ABC with AB < AC, let O be the "
        "circumcenter. Let XYZT be a parallelogram inside triangle ABC such that "
        "angle AXB = angle AZC, angle AZB = angle AXC, angle AYB = angle ATC, "
        "and angle ATB = angle AYC. Prove that the intersection of diagonals "
        "XZ and YT lies on the circumcircle of triangle BOC."
    ),
    domain="geometry",
    difficulty_level=6,
    difficulty_label="competition_extreme",
))

_register(ProblemSpec(
    problem_id="rmm2026_p6_permutation_floor_inequality",
    question=(
        "RMM 2026 Problem 6: Let k > 1 be an integer, and let S be the set of "
        "all (k+1)-tuples X = (x_1, ..., x_{k+1}) of integers with "
        "1 <= x_1 < ... < x_{k+1} <= k^2 + 1. For a permutation sigma of "
        "{1, 2, ..., k^2 + 1}, call an element X of S sigma-good if "
        "sigma(x_1), sigma(x_2), ..., sigma(x_{k+1}) is monotone. Prove that "
        "min_{1<=i<=k} floor(x_i / i) + min_{2<=i<=k+1} floor((k^2 + 2 - x_i) / (k + 2 - i)) >= k + 1 "
        "if and only if there exists a permutation sigma such that X is the "
        "unique sigma-good tuple in S."
    ),
    domain="combinatorics",
    difficulty_level=6,
    difficulty_label="competition_extreme",
))

_register(ProblemSpec(
    problem_id="erdos_338_restricted_order_basis",
    question=(
        "The restricted order of a basis is the least integer t (if it exists) "
        "such that every sufficiently large integer is the sum of at most t "
        "distinct summands from A. What are necessary and sufficient conditions "
        "for the restricted order to exist? Can it be bounded, when it exists, "
        "in terms of the order of the basis? What are necessary and sufficient "
        "conditions for the restricted order to equal the order of the basis?"
    ),
    domain="number_theory",
    difficulty_level=6,
    difficulty_label="research_extreme",
))

_register(ProblemSpec(
    problem_id="erdos_460_coprime_shift_greedy_sequence",
    question=(
        "For each integer n, let a_0 = 0 and a_1 = 1, and for k >= 2 define "
        "a_k to be the least integer greater than a_{k-1} such that "
        "gcd(n - a_k, n - a_i) = 1 for all 0 <= i < k. Does the sum of 1 / a_i "
        "over all indices with 0 < a_i < n tend to infinity as n tends to "
        "infinity? What happens if one restricts the sum to those i for which "
        "n - a_i is divisible by some prime at most a_i, or to the complementary "
        "set of indices?"
    ),
    domain="number_theory",
    difficulty_level=6,
    difficulty_label="research_extreme",
))

_register(ProblemSpec(
    problem_id="erdos_696_divisor_congruence_chains",
    question=(
        "Let h(n) be the largest ell such that there is a sequence of primes "
        "p_1 < ... < p_ell, all dividing n, with p_{i+1} congruent to 1 modulo "
        "p_i for every i. Let H(n) be the largest u such that there is a sequence "
        "of divisors d_1 < ... < d_u of n with d_{i+1} congruent to 1 modulo d_i "
        "for every i. Estimate h(n) and H(n). Is it true that H(n) / h(n) tends "
        "to infinity for almost all n?"
    ),
    domain="number_theory",
    difficulty_level=6,
    difficulty_label="research_extreme",
))

_register(ProblemSpec(
    problem_id="erdos_749_sparse_representation_dense_sumset",
    question=(
        "Let epsilon > 0. Does there exist a set A of positive integers such "
        "that the lower density of A + A is at least 1 - epsilon, yet the "
        "representation function 1_A * 1_A(n) is bounded above by a constant "
        "depending only on epsilon for all n?"
    ),
    domain="combinatorics",
    difficulty_level=6,
    difficulty_label="research_extreme",
))


# ---------------------------------------------------------------------------
# Suites
# ---------------------------------------------------------------------------

_SUITES: dict[str, list[str]] = {
    "demo": [
        "sum_first_n_odds",
        "square_expansion_commutative_ring",
        "difference_of_squares_commutative_ring",
        "difference_of_cubes_commutative_ring",
    ],
    "commutative_algebra_core": [
        "square_expansion_commutative_ring",
        "difference_of_squares_commutative_ring",
        "difference_of_cubes_commutative_ring",
    ],
    "number_theory_basics": [
        "sum_first_n_odds",
        "harmonic_sum_not_integer",
    ],
    "qualifying_exam": [
        "pid_prime_implies_maximal",
        "radical_intersection_product",
        "localization_preserves_intersection",
        "nakayama_zero_module_local",
        "compact_to_hausdorff_homeomorphism",
        "nonabelian_group_conjugacy_class_ratio",
        "two_dim_rep_eigenvalue_one_direct_sum",
        "five_lemma_abelian_groups",
        "group_order_150_not_simple",
    ],
    "level_4": [
        "hilbert_basis_theorem",
        "pid_torsion_free_module_free",
        "chinese_remainder_comaximal",
        "finite_dimensional_normed_space_complete",
        "projective_module_local_ring_free",
        "lebesgue_dominated_convergence",
        "open_mapping_theorem_banach",
        "uniform_boundedness_principle",
        "hahn_banach_extension",
        "galois_group_x8_minus_5",
        "sl2r_symmetric_power_irreducible",
        "pid_submodule_free_rank",
    ],
    "imo_2024": [
        "imo2024_a1_floor_sum_divisibility",
        "imo2024_a2_weighted_square_minimum",
        "imo2024_n1_divisor_plus_one",
        "imo2024_n2_divisibility_sets",
        "imo2024_n3_integral_means_sequence",
    ],
    "level_5_research": [
        "weak_nullstellensatz",
        "krull_intersection_theorem_local",
        "lasker_noether_primary_decomposition",
        "krein_milman_extreme_points",
        "polynomial_roots_mod_p_not_rational",
    ],
    "level_6": [
        "rmm2026_p5_parallelogram_circumcircle",
        "rmm2026_p6_permutation_floor_inequality",
        "erdos_338_restricted_order_basis",
        "erdos_460_coprime_shift_greedy_sequence",
        "erdos_696_divisor_congruence_chains",
        "erdos_749_sparse_representation_dense_sumset",
    ],
    "rmm_2026": [
        "rmm2026_p1_triangle_subdivision",
        "rmm2026_p2_factorial_divisibility",
        "rmm2026_p3_finite_set_polynomial_system",
        "rmm2026_p4_iterated_totient_prime_factors",
        "rmm2026_p5_parallelogram_circumcircle",
        "rmm2026_p6_permutation_floor_inequality",
    ],
    "benchmark_small_train": [
        "imo2024_n1_divisor_plus_one",
        "rmm2026_p2_factorial_divisibility",
    ],
    "benchmark_main_train": [
        "imo2024_n1_divisor_plus_one",
        "rmm2026_p2_factorial_divisibility",
        "rmm2026_p4_iterated_totient_prime_factors",
    ],
    "benchmark_holdout": [
        "rmm2026_p6_permutation_floor_inequality",
    ],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_problem(problem_id: str) -> ProblemSpec:
    """Return a *ProblemSpec* by its unique id.

    Raises ``KeyError`` if the id is not registered.
    """
    try:
        return _PROBLEMS[problem_id]
    except KeyError:
        raise KeyError(
            f"Unknown problem id {problem_id!r}. "
            f"Available: {sorted(_PROBLEMS)}"
        ) from None


def list_problems() -> list[str]:
    """Return problem ids sorted by difficulty (easiest first), then by id."""
    return [
        p.problem_id
        for p in sorted(
            _PROBLEMS.values(),
            key=lambda p: (p.difficulty_level, p.problem_id),
        )
    ]


def list_suites() -> dict[str, list[str]]:
    """Return a mapping of suite name -> list of problem ids."""
    return dict(_SUITES)


def load_suite(suite_name: str) -> list[ProblemSpec]:
    """Load every problem in the named suite.

    Raises ``KeyError`` if the suite name is unknown.
    """
    try:
        ids = _SUITES[suite_name]
    except KeyError:
        raise KeyError(
            f"Unknown suite {suite_name!r}. "
            f"Available: {sorted(_SUITES)}"
        ) from None
    return [load_problem(pid) for pid in ids]
