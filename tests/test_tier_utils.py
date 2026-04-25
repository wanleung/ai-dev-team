from agents.tier_utils import apply_tier_overrides


def test_no_rules_returns_unchanged():
    modules = [{"name": "app/models/user", "description": "User model", "tier": "junior"}]
    result = apply_tier_overrides(modules, [])
    assert result == modules


def test_exact_match_overrides_tier():
    modules = [{"name": "app/models/user", "description": "User model", "tier": "senior"}]
    rules = [{"pattern": "app/models/*", "tier": "junior"}]
    result = apply_tier_overrides(modules, rules)
    assert result[0]["tier"] == "junior"


def test_first_matching_rule_wins():
    modules = [{"name": "app/core/config", "description": "Config", "tier": "junior"}]
    rules = [
        {"pattern": "app/core*", "tier": "senior"},
        {"pattern": "app/*", "tier": "junior"},
    ]
    result = apply_tier_overrides(modules, rules)
    assert result[0]["tier"] == "senior"


def test_no_matching_rule_leaves_tier_unchanged():
    modules = [{"name": "app/services/auth", "description": "Auth service", "tier": "junior"}]
    rules = [{"pattern": "*/models*", "tier": "junior"}]
    result = apply_tier_overrides(modules, rules)
    assert result[0]["tier"] == "junior"


def test_multiple_modules_each_matched_independently():
    modules = [
        {"name": "app/models/user", "description": "User model", "tier": "senior"},
        {"name": "app/services/auth", "description": "Auth", "tier": "junior"},
    ]
    rules = [{"pattern": "*/models*", "tier": "junior"}]
    result = apply_tier_overrides(modules, rules)
    assert result[0]["tier"] == "junior"
    assert result[1]["tier"] == "junior"  # unchanged, no match


def test_missing_tier_field_defaults_to_senior():
    modules = [{"name": "app/services/auth", "description": "Auth"}]
    result = apply_tier_overrides(modules, [])
    assert result[0]["tier"] == "senior"
