from math_agent.problem.spec import load_problem, load_suite


def test_level_6_suite_includes_new_erdos_problems():
    suite = load_suite("level_6")
    ids = {problem.problem_id for problem in suite}

    assert "rmm2026_p5_parallelogram_circumcircle" in ids
    assert "rmm2026_p6_permutation_floor_inequality" in ids
    assert "erdos_338_restricted_order_basis" in ids
    assert "erdos_460_coprime_shift_greedy_sequence" in ids
    assert "erdos_696_divisor_congruence_chains" in ids
    assert "erdos_749_sparse_representation_dense_sumset" in ids


def test_new_erdos_level_6_problem_metadata():
    spec = load_problem("erdos_749_sparse_representation_dense_sumset")

    assert spec.difficulty_level == 6
    assert spec.difficulty_label == "research_extreme"
    assert spec.domain == "combinatorics"
