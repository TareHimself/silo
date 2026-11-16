import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from silo import cli
from silo.build_profile import Profile
from silo.enums import RuntimeLinkage
from silo.errors import SiloError
from silo.paths import profile_path
from silo.platform import check_runtime


@pytest.fixture
def settings_file(tmp_path):
    def write(text: str):
        path = tmp_path / "windows-static.toml"
        path.write_text(f"[settings]\n{text}\n", encoding="utf-8")
        return path

    return write


def test_a_file_with_settings_only_goes_over_the_default_profile(windows_profile, settings_file):
    windows_profile.save(profile_path("default"))

    loaded = Profile.load(settings_file('runtime = "static"'), base=profile_path("default"))

    assert loaded.settings.runtime is RuntimeLinkage.Static
    assert loaded.settings.cppstd == windows_profile.settings.cppstd
    assert loaded.compiler == windows_profile.compiler


def test_a_file_with_a_compiler_stands_alone(windows_profile, linux_profile, tmp_path):
    windows_profile.save(profile_path("default"))
    linux_profile.save(tmp_path / "linux.toml")

    loaded = Profile.load(tmp_path / "linux.toml", base=profile_path("default"))

    assert loaded == linux_profile


def test_settings_for_another_system_are_refused(linux_profile, settings_file):
    linux_profile.save(profile_path("default"))

    with pytest.raises(SiloError, match=r"is for windows, and the profile at .* is for linux"):
        Profile.load(settings_file('os = "windows"'), base=profile_path("default"))


def test_settings_need_a_default_profile_to_go_over(settings_file):
    with pytest.raises(SiloError, match="silo profile detect"):
        Profile.load(settings_file('runtime = "static"'), base=profile_path("default"))


def test_a_misspelled_setting_is_refused(windows_profile, settings_file):
    windows_profile.save(profile_path("default"))

    with pytest.raises(ValidationError, match="runtim"):
        Profile.load(settings_file('runtim = "static"'), base=profile_path("default"))


def test_a_misspelled_table_is_refused(windows_profile, tmp_path):
    windows_profile.save(profile_path("default"))
    misspelled = tmp_path / "misspelled.toml"
    misspelled.write_text('[setting]\nruntime = "static"\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="setting"):
        Profile.load(misspelled, base=profile_path("default"))


def test_a_static_runtime_is_refused_where_the_compiler_has_one_only(
    windows_profile, linux_profile, macos_profile
):
    for profile in (windows_profile, linux_profile, macos_profile):
        profile.settings.runtime = RuntimeLinkage.Static

    check_runtime(windows_profile)
    with pytest.raises(SiloError, match="gcc on linux links one runtime only"):
        check_runtime(linux_profile)
    with pytest.raises(SiloError, match="apple_clang on macos links one runtime only"):
        check_runtime(macos_profile)


def test_a_command_takes_a_profile_file(windows_profile, settings_file, load_demo_recipe):
    windows_profile.save(profile_path("default"))
    recipe_dir = load_demo_recipe().recipe_dir
    static = settings_file('runtime = "static"')
    misspelled = static.with_name("misspelled.toml")
    misspelled.write_text('[settings]\nruntim = "static"\n', encoding="utf-8")

    built = CliRunner().invoke(cli.app, ["graph", str(recipe_dir), "-p", str(static)])
    refused = CliRunner().invoke(cli.app, ["graph", str(recipe_dir), "-p", str(misspelled)])

    assert built.exit_code == 0, built.output
    assert refused.exit_code == 1
    assert "runtim" in refused.output
