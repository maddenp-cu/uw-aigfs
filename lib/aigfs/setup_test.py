from pathlib import Path
from unittest.mock import Mock, patch

from pytest import mark, raises
from uwtools.api.config import YAMLConfig

from aigfs import setup
from aigfs.common import HOMEDIR
from aigfs.strings import STR

ECFLOW_BASE_YAML = setup.ETCDIR / STR.workflow / "ecflow.yaml"
INCLUDE_DIR = HOMEDIR / "include"


def test_setup_ECFLOW_BASE_YAML__post_trigger():
    text = ECFLOW_BASE_YAML.read_text()
    assert "trigger: prep == complete" in text
    assert "trigger: '../forecast:release_{{ ec.fhr }}'" in text


def test_setup_ECFLOW_BASE_YAML__release_events():
    # aigfs.drivers.inference emits per-leadtime release_f{fff} events via post_write_hook.
    text = ECFLOW_BASE_YAML.read_text()
    assert "release_f%03d" in text
    assert "events:" in text


def test_setup_ECFLOW_BASE_YAML__post_write_hook():
    text = ECFLOW_BASE_YAML.read_text()
    assert (
        "post_write_hook: 'ecflow_client --alter change event "
        'release_f$(printf "%03d" $LEADTIME) set $ECF_NAME\'' in text
    )


def test_setup_ECFLOW_BASE_YAML__server_defaults():
    text = ECFLOW_BASE_YAML.read_text()
    assert "  server:\n    ECF_HOME: '{{ app.rundir }}/ecf'" in text


def test_setup_INCLUDE_DIR__ecflow_head_uses_ssl_and_slurm_job_id():
    text = (INCLUDE_DIR / "head.h").read_text()
    assert 'test -n "%ECF_SSL:%" && export ECF_SSL=%ECF_SSL:%' in text
    assert "export ECF_RID=$%RID_VAR%" in text
    assert "ecflow_client --init=$ECF_RID" in text
    assert "ecflow_client --abort=trap" in text


def test_setup_INCLUDE_DIR__ecflow_tail_uses_ssl():
    text = (INCLUDE_DIR / "tail.h").read_text()
    assert "ecflow_client --complete" in text


@mark.parametrize("workflow", ["rocoto", "ecflow", None])
def test_setup_compose_configs(logcap, tmp_path, workflow):
    platform = "ursa"
    user_config_files = [Path("/path/to/a.yaml")]
    with (
        patch.object(setup, "compose_to_dict") as compose_to_dict,
        patch.object(setup, "NamedTemporaryFile") as NamedTemporaryFile,
    ):
        compose_to_dict.return_value = {STR.app: {STR.rundir: "/some/path"}}
        reserved_path = tmp_path / "reserved.yaml"
        tmp = Mock()
        tmp.name = str(reserved_path)
        NamedTemporaryFile().__enter__.return_value = tmp
        result = setup.compose_configs(workflow, platform, user_config_files)
    assert result == {STR.app: {STR.rundir: "/some/path"}}
    workflow_configs = [setup.ETCDIR / STR.workflow / f"{workflow}.yaml"] if workflow else []
    compose_to_dict.assert_called_once_with(
        [
            setup.ETCDIR / STR.base_yaml,
            *workflow_configs,
            setup.PLATFORMDIR / "ursa.yaml",
            Path("/path/to/a.yaml"),
            reserved_path,
        ],
        realize=True,
    )
    expected = {STR.app: {STR.home: str(setup.HOMEDIR), STR.platform: {STR.name: "ursa"}}}
    assert YAMLConfig(reserved_path) == expected
    msg = "No --workflow value supplied, omitting workflow support"
    assert (msg in logcap.text) == (workflow is None)


@mark.parametrize("workflow", ["rocoto", "ecflow", None])
def test_setup_main(workflow):
    with (
        patch.object(setup, "compose_configs") as compose_configs,
        patch.object(setup, "parse_args") as parse_args,
        patch.object(setup, "set_up_rundir") as set_up_rundir,
        patch.object(setup, "use_uwtools_logger") as use_uwtools_logger,
        patch.object(setup, "validate") as validate,
    ):
        args = Mock(
            platform="ursa",
            verbose=True,
            workflow=workflow,
            user_config_files=[Path("/path/to/a.yaml")],
        )
        parse_args.return_value = args
        compose_configs.return_value = {STR.app: {"key": "val"}}
        setup.main()
        parse_args.assert_called_once_with()
        use_uwtools_logger.assert_called_once_with(verbose=True)
        compose_configs.assert_called_once_with(workflow, "ursa", [Path("/path/to/a.yaml")])
        config = {STR.app: {"key": "val"}}
        validate.assert_called_once_with(config)
        set_up_rundir.assert_called_once_with(config, workflow)


@mark.parametrize(
    ("argv", "expected_platform", "expected_workflow", "expected_files", "expected_verbose"),
    [
        (
            ["--platform", "ursa", "--workflow", "rocoto", "/path/to/a.yaml", "/path/to/b.yaml"],
            "ursa",
            "rocoto",
            [Path("/path/to/a.yaml"), Path("/path/to/b.yaml")],
            False,
        ),
        (
            ["--platform", "ursa", "/path/to/a.yaml", "--workflow", "ecflow"],
            "ursa",
            "ecflow",
            [Path("/path/to/a.yaml")],
            False,
        ),
        (
            ["--workflow", "ecflow", "--platform", "ursa", "/path/to/a.yaml"],
            "ursa",
            "ecflow",
            [Path("/path/to/a.yaml")],
            False,
        ),
        (
            ["--platform", "oci", "--verbose", "/path/to/a.yaml"],
            "oci",
            None,
            [Path("/path/to/a.yaml")],
            True,
        ),
    ],
)
def test_setup_parse_args(
    argv, expected_platform, expected_workflow, expected_files, expected_verbose
):
    with (
        patch.object(setup, "platforms", return_value=["oci", "ursa"]),
        patch("sys.argv", ["prog", *argv]),
    ):
        result = setup.parse_args()
    assert result.platform == expected_platform
    assert result.workflow == expected_workflow
    assert result.user_config_files == expected_files
    assert result.verbose == expected_verbose


def test_setup_set_up_rundir(logcap, tmp_path):
    rundir = tmp_path / STR.rundir
    config: dict = {STR.app: {STR.rundir: str(rundir)}}
    with (
        patch.object(setup, "YAMLConfig") as YAMLConfig,
        patch.object(setup, "rocoto") as rocoto,
    ):
        rocoto.realize.return_value = True
        setup.set_up_rundir(config, "rocoto")
    assert rundir.is_dir()
    assert YAMLConfig.call_args_list[0].args[0] == config
    assert YAMLConfig.call_args_list[1].args[0] == config
    YAMLConfig.return_value.dump.assert_called_once_with(rundir / STR.aigfs_yaml)
    rocoto.realize.assert_called_once_with(YAMLConfig(config), rundir / STR.rocoto_xml)
    assert f"AIGFS will be set up here: {rundir}" in logcap.text


def test_setup_set_up_rundir__ecflow(logcap, tmp_path):
    rundir = tmp_path / STR.rundir
    config: dict = {STR.app: {STR.rundir: str(rundir)}}
    with (
        patch.object(setup, "YAMLConfig") as YAMLConfig,
        patch.object(setup, "ecflow") as ecflow,
    ):
        setup.set_up_rundir(config, "ecflow")
    assert rundir.is_dir()
    assert YAMLConfig.call_args_list[0].args[0] == config
    assert YAMLConfig.call_args_list[1].args[0] == config
    YAMLConfig.return_value.dump.assert_called_once_with(rundir / STR.aigfs_yaml)
    ecflow.realize.assert_called_once_with(YAMLConfig(config), rundir, scripts_path=rundir / "ecf")
    assert f"AIGFS will be set up here: {rundir}" in logcap.text


def test_setup_set_up_rundir__invalid_xml(logcap, tmp_path):
    rundir = tmp_path / STR.rundir
    config: dict = {STR.app: {STR.rundir: str(rundir)}}
    with (
        patch.object(setup, "YAMLConfig"),
        patch.object(setup, "rocoto") as rocoto,
    ):
        rocoto.realize.return_value = False
        with raises(SystemExit):
            setup.set_up_rundir(config, "rocoto")
    assert "Invalid Rocoto XML" in logcap.text


def test_setup_set_up_rundir__no_workflow(logcap, tmp_path):
    rundir = tmp_path / STR.rundir
    config: dict = {STR.app: {STR.rundir: str(rundir)}}
    with (
        patch.object(setup, "YAMLConfig") as YAMLConfig,
        patch.object(setup, "ecflow") as ecflow,
        patch.object(setup, "rocoto") as rocoto,
    ):
        setup.set_up_rundir(config, None)
    assert rundir.is_dir()
    YAMLConfig.return_value.dump.assert_called_once_with(rundir / STR.aigfs_yaml)
    ecflow.realize.assert_not_called()
    rocoto.realize.assert_not_called()
    assert f"AIGFS will be set up here: {rundir}" in logcap.text
