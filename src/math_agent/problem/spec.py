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
# Built-in problems  (34 unique entries)
# ---------------------------------------------------------------------------

_PROBLEMS: dict[str, ProblemSpec] = {}


def _register(spec: ProblemSpec) -> None:
    _PROBLEMS[spec.problem_id] = spec


# --- difficulty 1 (toy) ---------------------------------------------------

_register(ProblemSpec(
    problem_id="sum_first_n_odds",
    question="Find a pattern for the sum of the first n odd numbers.",
    domain="elementary_number_theory",
    difficulty_level=1,
    difficulty_label="toy",
))

_register(ProblemSpec(
    problem_id="square_expansion_commutative_ring",
    question="In a commutative ring, expand (x + y)^2 as a polynomial in x and y.",
    domain="commutative_algebra",
    difficulty_level=1,
    difficulty_label="toy",
))

_register(ProblemSpec(
    problem_id="difference_of_squares_commutative_ring",
    question="In a commutative ring, simplify (x + y)(x - y).",
    domain="commutative_algebra",
    difficulty_level=1,
    difficulty_label="toy",
))

_register(ProblemSpec(
    problem_id="difference_of_cubes_commutative_ring",
    question="In a commutative ring, factor x^3 - y^3.",
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
        "Prove that if R is Noetherian, then R[x] is Noetherian."
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
    question="Prove the Lebesgue Dominated Convergence Theorem.",
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="open_mapping_theorem_banach",
    question="Prove the Open Mapping Theorem for Banach spaces.",
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="uniform_boundedness_principle",
    question="Prove the Uniform Boundedness Principle.",
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="hahn_banach_extension",
    question="Prove the Hahn-Banach Extension Theorem.",
    domain="analysis",
    difficulty_level=4,
    difficulty_label="beyond_qe",
))

_register(ProblemSpec(
    problem_id="galois_group_x8_minus_5",
    question="Compute the Galois group of x^8 - 5 over Q.",
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
    question="IMO 2024 A1: floor sum divisibility.",
    domain="algebra",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

_register(ProblemSpec(
    problem_id="imo2024_a2_weighted_square_minimum",
    question="IMO 2024 A2: weighted square minimum.",
    domain="algebra",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

_register(ProblemSpec(
    problem_id="imo2024_n1_divisor_plus_one",
    question="IMO 2024 N1: divisor plus one.",
    domain="number_theory",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

_register(ProblemSpec(
    problem_id="imo2024_n2_divisibility_sets",
    question="IMO 2024 N2: divisibility sets.",
    domain="number_theory",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

_register(ProblemSpec(
    problem_id="imo2024_n3_integral_means_sequence",
    question="IMO 2024 N3: integral means sequence.",
    domain="number_theory",
    difficulty_level=4,
    difficulty_label="olympiad_longproof",
))

# --- difficulty 5 (research) ----------------------------------------------

_register(ProblemSpec(
    problem_id="weak_nullstellensatz",
    question="Prove the Weak Nullstellensatz.",
    domain="algebraic_geometry",
    difficulty_level=5,
    difficulty_label="research",
))

_register(ProblemSpec(
    problem_id="krull_intersection_theorem_local",
    question="Prove the Krull Intersection Theorem for local rings.",
    domain="commutative_algebra",
    difficulty_level=5,
    difficulty_label="research",
))

_register(ProblemSpec(
    problem_id="lasker_noether_primary_decomposition",
    question="Prove the Lasker-Noether Primary Decomposition.",
    domain="commutative_algebra",
    difficulty_level=5,
    difficulty_label="research",
))

_register(ProblemSpec(
    problem_id="krein_milman_extreme_points",
    question="Prove the Krein-Milman Theorem.",
    domain="analysis",
    difficulty_level=5,
    difficulty_label="research",
))

_register(ProblemSpec(
    problem_id="polynomial_roots_mod_p_not_rational",
    question=(
        "Prove the Chebotarev density criterion for roots mod p."
    ),
    domain="algebra",
    difficulty_level=5,
    difficulty_label="research",
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
    """Return a sorted list of all registered problem ids."""
    return sorted(_PROBLEMS)


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
