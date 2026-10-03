"""diversion.set_generated_rules: managed rules run before the rules file and survive its reloads."""

import pytest

from logitech_receiver import diversion


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    path = tmp_path / "rules.yaml"
    monkeypatch.setattr(diversion, "_file_path", str(path))
    monkeypatch.setattr(diversion, "rules", diversion.built_in_rules)
    monkeypatch.setattr(diversion, "_loaded_rules", diversion.built_in_rules)
    monkeypatch.setattr(diversion, "_generated_rules", None)
    return path


USER_RULE = "%YAML 1.3\n---\n- Key: [Haptic, pressed]\n- KdeShortcut: [kwin, Expose]\n...\n"


def _generated():
    return diversion.Rule([diversion.Rule([{"Key": ["Haptic", "pressed"]}, {"KdeShortcut": ["kwin", "Overview"]}])])


def test_generated_rules_come_first(rules_file):
    rules_file.write_text(USER_RULE)
    diversion.reload_config_rule_file()
    user = diversion.rules.components[0]
    generated = _generated()

    diversion.set_generated_rules(generated)

    assert diversion.rules.components == [generated, user, diversion.built_in_rules]


def test_reloading_the_rules_file_keeps_generated_rules(rules_file):
    generated = _generated()
    diversion.set_generated_rules(generated)
    rules_file.write_text(USER_RULE)

    diversion.reload_config_rule_file()

    assert diversion.rules.components[0] is generated
    assert diversion.rules.components[1].source == str(rules_file)


def test_generated_rules_without_rules_file(rules_file):
    generated = _generated()

    diversion.set_generated_rules(generated)
    assert diversion.rules.components == [generated, diversion.built_in_rules]

    rules_file.write_text(USER_RULE)
    diversion.reload_config_rule_file()
    rules_file.unlink()
    diversion.reload_config_rule_file()
    assert diversion.rules.components == [generated, diversion.built_in_rules]


def test_removing_generated_rules_restores_the_usual_shape(rules_file):
    diversion.set_generated_rules(_generated())

    diversion.set_generated_rules(None)
    assert diversion.rules is diversion.built_in_rules

    rules_file.write_text(USER_RULE)
    diversion.load_config_rule_file()
    diversion.set_generated_rules(None)
    assert diversion.rules.components[0].source == str(rules_file)
    assert diversion.rules.components[1] is diversion.built_in_rules


def test_saving_the_rules_file_leaves_generated_rules_out(rules_file):
    rules_file.write_text(USER_RULE)
    diversion.reload_config_rule_file()
    diversion.set_generated_rules(diversion.Rule([_generated()], source="/elsewhere/buttons.yaml"))

    diversion._save_config_rule_file(str(rules_file))

    text = rules_file.read_text()
    assert "Expose" in text
    assert "Overview" not in text
