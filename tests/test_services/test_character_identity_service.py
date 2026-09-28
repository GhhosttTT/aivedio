from src.services.character_identity_service import CharacterIdentityService, load_identity_spec


def test_identity_specs_are_stable_and_distinct_for_same_project():
    service = CharacterIdentityService()
    first = service.build_identity_spec("林安", "女主", "敏感果断", project_id=7)
    repeated = service.build_identity_spec("林安", "女主", "敏感果断", project_id=7)
    second = service.build_identity_spec("顾沉", "男主", "克制冷静", project_id=7, existing_specs=[first])

    assert first == repeated
    assert first["identity_anchor"].startswith("林安:")
    report = service.distinctiveness_report([first, second])
    assert report["status"] == "passed"
    assert report["pairs"][0]["distance"] >= 0.72


def test_identity_specs_remain_distinct_for_large_cast():
    service = CharacterIdentityService()
    specs = []
    for index, name in enumerate(["林安", "顾沉", "宁夏", "周砚", "苏禾", "陆川", "许沫", "江野", "唐梨", "沈既白"]):
        specs.append(
            service.build_identity_spec(
                name,
                role=f"角色{index}",
                personality=f"性格{index}",
                project_id=12,
                existing_specs=specs,
            )
        )

    report = service.distinctiveness_report(specs)

    assert report["status"] == "passed"
    assert len(report["pairs"]) == 45
    assert min(pair["distance"] for pair in report["pairs"]) >= 0.72


def test_prompt_pack_contains_requested_languages_and_negative_identity():
    service = CharacterIdentityService()
    spec = service.build_identity_spec("阿澈", project_id=9)
    pack = service.prompt_pack(spec, ["zh", "en", "ko"])

    assert set(pack["languages"]) == {"zh", "en", "ko"}
    assert spec["hair"] in pack["languages"]["en"]["scene_prefix"]
    assert "no changed eye shape" in pack["languages"]["zh"]["negative"]


def test_identity_contrast_prompt_lists_pairwise_facial_differences():
    service = CharacterIdentityService()
    first = service.build_identity_spec("林安", "女主", project_id=7)
    second = service.build_identity_spec("顾沉", "男主", project_id=7, existing_specs=[first])

    prompt = service.identity_contrast_prompt([first, second])

    assert "Identity contrast contract" in prompt
    assert "林安 must not look like 顾沉" in prompt
    assert " vs " in prompt
    assert "same-face" in prompt


def test_identity_contrast_matrix_lists_pairwise_feature_values():
    service = CharacterIdentityService()
    first = service.build_identity_spec("林安", "女主", project_id=7)
    second = service.build_identity_spec("顾沉", "男主", project_id=7, existing_specs=[first])

    matrix = service.identity_contrast_matrix([first, second])

    assert matrix["status"] == "passed"
    assert matrix["characters"][0]["name"] == "林安"
    assert matrix["pairs"][0]["left"] == "林安"
    assert matrix["pairs"][0]["right"] == "顾沉"
    assert matrix["pairs"][0]["contrast_fields"]
    assert {"field", "left", "right"} <= set(matrix["pairs"][0]["contrast_fields"][0])
    assert "same-face" in matrix["pairs"][0]["must_keep_apart"]


def test_score_observed_spec_quantifies_feature_mismatch():
    service = CharacterIdentityService()
    expected = service.build_identity_spec("宁夏", project_id=3)
    observed = dict(expected)
    observed["nose"] = "flat triangle profile"
    observed["mouth"] = ""

    result = service.score_observed_spec(expected, observed)

    assert result["status"] == "needs_review"
    assert result["scores"]["eyes"]["score"] == 5
    assert result["scores"]["nose"]["score"] == 1
    assert result["scores"]["mouth"]["score"] == 0


def test_load_identity_spec_rejects_non_identity_json():
    assert load_identity_spec('{"version": 1, "name": "x"}') == {"version": 1, "name": "x"}
    assert load_identity_spec('{"name": "x"}') is None
    assert load_identity_spec("plain text") is None
