import fcntl
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import ANY, Mock, patch

from iotaa import Asset
from pydantic import ValidationError
from pytest import fixture, mark, raises

from aigfs import workflow
from aigfs.drivers.inference import AIGFSInference
from aigfs.strings import STR

# Fixtures


@fixture
def cfg(tmp_path):
    path = tmp_path / "aigfs.yaml"
    with patch.object(workflow, "CONFIG", path), patch.object(workflow, "APPDIR", tmp_path):
        yield path


@fixture
def workflow_config(tmp_path):
    return {
        "app": {
            "cycle_freq": timedelta(hours=12),
            "first_cycle": datetime(2026, 1, 1, tzinfo=UTC),
            "home": tmp_path,
            "last_cycle": datetime(2026, 1, 31, tzinfo=UTC),
            "modeldir": tmp_path,
            "platform": {"name": "ursa"},
            "rundir": tmp_path,
            "time": {
                "fff": "006",
                "hh": "00",
                "m1_hh": "18",
                "m1_yyyymmdd": "20260826",
                "m2_hh": "12",
                "m2_yyyymmdd": "20260826",
                "m6h": timedelta(hours=6),
                "yyyymmdd": "20260827",
            },
        },
        "forecast": {},
        "post": {},
        "prep": {},
        "user": {},
    }


@fixture
def cycle(utc):
    return utc(2025, 10, 1, 18)


@fixture
def gribfiles(tmp_path):
    return [
        tmp_path / ("aigfs.t18z.%s.f%03d.grib2" % (kind, hour))
        for hour in (6, 12)
        for kind in (STR.pres, STR.sfc)
    ]


@fixture
def lockkit(tmp_path):
    rundir = tmp_path / "run"
    output = tmp_path / "out"
    obj = Mock(rundir=rundir)
    obj.run.side_effect = lambda *_, **_k: output.touch()
    assets = [Asset(output, output.is_file)]
    return obj, assets, rundir / ".lock-20251001-18Z-012-post", output


TASKNAME = "20251001 18Z 012 post"


def driver(output: dict, rundir: Path) -> Mock:
    obj = Mock(output=output, rundir=rundir)
    return Mock(return_value=obj)


# Tests


def test_workflow_AppCycles(workflow_config):
    app = workflow.AppCycles.model_validate(workflow_config["app"])
    assert app.cycle_freq == timedelta(hours=12)
    assert app.first_cycle == workflow_config["app"]["first_cycle"]
    assert app.last_cycle == workflow_config["app"]["last_cycle"]


@mark.parametrize(
    ("field", "value"),
    [
        ("cycle_freq", "not-a-timedelta"),
        ("first_cycle", "not-a-datetime"),
        ("last_cycle", "not-a-datetime"),
    ],
)
def test_workflow_AppCycles__bad_and_missing(field, value, with_del, with_set, workflow_config):
    # Bad:
    with raises(ValidationError) as e:
        workflow.AppCycles.model_validate(with_del(workflow_config["app"], field))
    assert e.value.errors()[0]["loc"] == (field,)
    # Missing:
    with raises(ValidationError) as e:
        workflow.AppCycles.model_validate(with_set(workflow_config["app"], value, field))
    assert e.value.errors()[0]["loc"] == (field,)


def test_workflow_AppRealtime(workflow_config):
    app_data = workflow_config["app"]
    del app_data["first_cycle"]
    del app_data["last_cycle"]
    app = workflow.AppRealtime.model_validate(app_data)
    assert app.cycle_freq == timedelta(hours=12)
    assert app.first_cycle is None
    assert app.last_cycle is None


@mark.parametrize(("field", "value"), [("cycle_freq", "not-a-timedelta"), ("cycle_freq", None)])
def test_workflow_AppRealtime__bad_and_mmissing(with_del, with_set, workflow_config, field, value):
    # Bad:
    with raises(ValidationError) as e:
        workflow.AppRealtime.model_validate(with_set(workflow_config["app"], value, field))
    assert e.value.errors()[0]["loc"] == (field,)
    # Missing:
    with raises(ValidationError) as e:
        workflow.AppRealtime.model_validate(with_del(workflow_config["app"], "cycle_freq"))
    assert e.value.errors()[0]["loc"] == ("cycle_freq",)


def test_workflow_User__optional_window_prune():
    user = workflow.User(window_size=3)
    assert user.window_size == 3
    assert user.window_prune is False


@mark.parametrize(
    ("model", "app_model", "optional_cycles"),
    [
        (workflow.ConfigCycles, workflow.AppCycles, False),
        (workflow.ConfigRealtime, workflow.AppRealtime, True),
    ],
)
def test_workflow_Config(workflow_config, model, app_model, optional_cycles):
    workflow_config["user"] = {"extra_setting": ["ok"], "window_prune": False, "window_size": 3}
    if optional_cycles:
        del workflow_config["app"]["first_cycle"]
        del workflow_config["app"]["last_cycle"]
    config = model.model_validate(workflow_config)
    assert isinstance(config.app, app_model)
    assert config.user.model_dump() == workflow_config["user"]


@mark.parametrize("user", [{}, {"window_size": True}, {"window_size": 3, "window_prune": 1}])
def test_workflow_Config__user_bad(workflow_config, user):
    workflow_config["user"] = user
    with raises(ValidationError):
        workflow.ConfigCycles.model_validate(workflow_config)


def test_workflow_Config__user_missing(with_del, workflow_config):
    with raises(ValidationError):
        workflow.ConfigCycles.model_validate(with_del(workflow_config, "user"))


@mark.parametrize("field", ["first_cycle", "last_cycle"])
def test_workflow_ConfigCycles__cycle_missing(with_del, workflow_config, field):
    config = with_del(workflow_config, "app", field)
    with raises(ValidationError) as e:
        workflow.ConfigCycles.model_validate(config)
    assert e.value.errors()[0]["loc"] == ("app", field)


@mark.parametrize(
    ("field", "value"),
    [
        ("cycle_freq", "not-a-timedelta"),
        ("first_cycle", "not-a-datetime"),
        ("last_cycle", "not-a-datetime"),
    ],
)
@mark.parametrize("model", [workflow.ConfigCycles, workflow.ConfigRealtime])
def test_workflow_Config__bad_app_types(with_set, workflow_config, model, field, value):
    config = with_set(workflow_config, value, "app", field)
    with raises(ValidationError) as e:
        model.model_validate(config)
    assert e.value.errors()[0]["loc"] == ("app", field)


def test_workflow_config__exists(cfg, touch):
    touch(cfg)
    with patch.object(workflow, "setup") as setup:
        node = workflow.config()
    assert node.ready
    assert node.taskname == "config"
    setup.compose_configs.assert_not_called()


@mark.usefixtures("cfg")
def test_workflow_config__missing(tmp_path):
    with patch.object(workflow, "setup") as setup:
        node = workflow.config()
    assert not node.ready
    setup.compose_configs.assert_called_once_with(
        workflow=None, platform="oci", user_config_files=[tmp_path / "user.yaml"]
    )
    c = setup.compose_configs.return_value
    setup.validate.assert_called_once_with(c)
    setup.set_up_rundir.assert_called_once_with(c, workflow=None, prefix="config")


@mark.parametrize("ready", [True, False])
def test_workflow_cycle(atask, cycle, ready):
    with patch.object(workflow, STR.post, Mock(wraps=lambda _: atask(ready))) as post:
        node = workflow.cycle(cycle)
    assert node.ready is ready
    assert node.taskname == "20251001 18Z cycle"
    post.assert_called_once_with(cycle)


@mark.parametrize("ready", [True, False])
def test_workflow_cycles(atask, cycle, ready):
    config = workflow.ConfigCycles.model_construct(
        app=workflow.AppCycles.model_construct(
            first_cycle=cycle,
            last_cycle=cycle + timedelta(hours=12),
            cycle_freq=timedelta(hours=6),
        )
    )
    with (
        patch.object(workflow, "_config", return_value=config),
        patch.object(workflow, "cycle", Mock(wraps=lambda _: atask(ready))) as cycle_,
    ):
        node = workflow.cycles()
    assert node.ready is ready
    assert node.taskname == "cycles"
    assert [c.args for c in cycle_.call_args_list] == [
        (cycle + timedelta(hours=12),),  # leading-edge first
        (cycle + timedelta(hours=6),),
        (cycle,),
    ]


@mark.parametrize("prune", [True, False])
def test_workflow_realtime(atask, tmp_path, prune):
    cycles = [tmp_path / f"20261010{hh}" for hh in ("00", "06", "12")]
    for path in cycles:
        path.mkdir()
    old_cycle = cycles.pop(0)
    app = workflow.AppRealtime.model_construct(
        cycle_freq=timedelta(hours=6),
        first_cycle=datetime(2026, 1, 1, tzinfo=UTC),
        last_cycle=datetime(2026, 1, 2, tzinfo=UTC),
        rundir=tmp_path,
    )
    user = workflow.User(window_prune=prune, window_size=2)
    config = workflow.ConfigRealtime.model_construct(app=app, user=user)
    with (
        patch.object(workflow, "_config", return_value=config),
        patch.object(workflow, "cycle", Mock(wraps=lambda _: atask(ready=True))) as cycle,
    ):
        node = workflow.realtime()
    assert node.ready
    assert node.taskname == "2 realtime cycles"
    active = [call.args[0] for call in cycle.call_args_list]
    assert len(active) == 2
    assert active[0].tzinfo is UTC
    assert active[0] - active[1] == timedelta(hours=6)
    assert old_cycle.is_dir() is not prune
    assert all(path.is_dir() for path in cycles)


@mark.parametrize(
    ("model", "expected_type"),
    [
        (workflow.ConfigCycles, workflow.ConfigCycles),
        (workflow.ConfigRealtime, workflow.ConfigRealtime),
    ],
)
def test_workflow__config(workflow_config, model, expected_type):
    workflow_config["user"] = {"window_size": 2}
    with patch.object(workflow, "realize_to_dict", return_value=workflow_config) as realize:
        workflow._config.cache_clear()
        try:
            config = workflow._config(model)
            assert isinstance(config, expected_type)
            realize.assert_called_once_with(workflow.CONFIG)
        finally:
            workflow._config.cache_clear()


@mark.parametrize("ready", [True, False])
def test_workflow_forecast(atask, cfg, cycle, gribfiles, ready, tmp_path):
    cls = driver({STR.forecast: gribfiles}, tmp_path / "run")
    with (
        patch.object(workflow, "AIGFSInference", cls),
        patch.object(workflow, "_schema", return_value=Path("/s")),
        patch.object(workflow, "prep", Mock(wraps=lambda _: atask(ready))) as prep,
        patch.object(workflow, "run_shell_cmd") as run_shell_cmd,
    ):
        if ready:
            run_shell_cmd.side_effect = lambda *_, **_k: [
                gribfile.touch() for gribfile in gribfiles
            ]
        node = workflow.forecast(cycle)
    assert node.taskname == "20251001 18Z forecast"
    cls.assert_called_once_with(
        cycle=cycle, config=cfg, key_path=[STR.forecast], schema_file=Path("/s")
    )
    prep.assert_called_once_with(cycle)
    assert node.ready is ready
    if ready:
        run_shell_cmd.assert_called_once_with(
            ANY, callback=ANY, cwd=cls.return_value.rundir, taskname="20251001 18Z forecast"
        )
    else:
        run_shell_cmd.assert_not_called()


@mark.parametrize("ready", [True, False])
def test_workflow_post(atask, cfg, cycle, gribfiles, ready, tmp_path):
    cls = driver({STR.forecast: gribfiles}, tmp_path / "run")
    with (
        patch.object(workflow, "AIGFSInference", cls),
        patch.object(workflow, "_schema", return_value=Path("/s")),
        patch.object(
            workflow, "_post_one_leadtime", Mock(wraps=lambda *_: atask(ready=ready))
        ) as _post_one_leadtime,
    ):
        node = workflow.post(cycle)
    assert node.ready is ready
    assert node.taskname == "20251001 18Z post"
    cls.assert_called_once_with(
        cycle=cycle, config=cfg, key_path=[STR.forecast], schema_file=Path("/s")
    )
    for pres, sfc in zip(gribfiles[::2], gribfiles[1::2], strict=True):
        _post_one_leadtime.assert_any_call(cycle, pres, sfc)


@mark.parametrize("ready", [True, False])
def test_workflow_prep(atask, cfg, cycle, ready, tmp_path):
    ics = tmp_path / "ics.nc"
    cls = driver({"ics": ics}, tmp_path / "run")
    with (
        patch.object(workflow, "AIGFSICs", cls),
        patch.object(workflow, "_schema", return_value=Path("/s")),
        patch.object(workflow, "_timegate", Mock(wraps=lambda _: atask(ready))) as _timegate,
        patch.object(workflow, "run_shell_cmd") as run_shell_cmd,
    ):
        if ready:
            run_shell_cmd.side_effect = lambda *_, **_k: ics.touch()
        node = workflow.prep(cycle)
    assert node.taskname == "20251001 18Z prep"
    cls.assert_called_once_with(
        cycle=cycle, config=cfg, key_path=[STR.prep], schema_file=Path("/s")
    )
    _timegate.assert_called_once_with(cycle)
    assert node.ready is ready
    if ready:
        run_shell_cmd.assert_called_once_with(
            ANY, callback=ANY, cwd=cls.return_value.rundir, taskname="20251001 18Z prep"
        )
    else:
        run_shell_cmd.assert_not_called()


@mark.parametrize("ready", [True, False])
def test_workflow__forecast_one_leadtime(atask, cycle, gribfiles, ready, touch):
    pres, sfc = gribfiles[:2]
    if ready:
        touch(pres)
        touch(sfc)
    with patch.object(workflow, STR.forecast, Mock(wraps=lambda _: atask(ready=True))) as forecast:
        node = workflow._forecast_one_leadtime(cycle, pres, sfc)
    assert node.taskname == "20251001 18Z 006 forecast"
    assert node.ready is ready
    forecast.assert_called_once_with(cycle)


@mark.parametrize("deliver", [True, False])
@mark.parametrize("ready", [True, False])
def test_workflow__post_one_leadtime(atask, cfg, cycle, deliver, gribfiles, ready, tmp_path):
    pres, sfc = gribfiles[2:]
    names = [f"{x.name}.idx" for x in (pres, sfc)]
    output = {STR.idx: [tmp_path / STR.post / x for x in names]}
    if deliver:
        output[STR.delivered] = [tmp_path / "delivery" / x for x in names]
    expected = output[STR.delivered] if deliver else output[STR.idx]
    for x in expected:
        x.parent.mkdir(parents=True, exist_ok=True)
    cls = driver(output, tmp_path / "run")
    with (
        patch.object(workflow, "AIGFSPost", cls),
        patch.object(workflow, "_schema", return_value=Path("/s")),
        patch.object(
            workflow, "_forecast_one_leadtime", Mock(wraps=lambda *_: atask(ready))
        ) as _forecast_one_leadtime,
        patch.object(workflow, "run_shell_cmd") as run_shell_cmd,
    ):
        if ready:
            run_shell_cmd.side_effect = lambda *_, **_k: [x.touch() for x in expected]
        node = workflow._post_one_leadtime(cycle, pres, sfc)
    assert node.taskname == "20251001 18Z 012 post"
    _forecast_one_leadtime.assert_called_once_with(cycle, pres, sfc)
    assert node.ready is ready
    cls.assert_called_once_with(
        cycle=cycle,
        leadtime=timedelta(hours=12),
        config=cfg,
        key_path=[STR.post],
        schema_file=Path("/s"),
    )
    if ready:
        run_shell_cmd.assert_called_once_with(
            ANY, callback=ANY, cwd=cls.return_value.rundir, taskname="20251001 18Z 012 post"
        )
    else:
        run_shell_cmd.assert_not_called()


@mark.parametrize(("hours", "ready"), [(-4, True), (0, False)])
def test_workflow__timegate(hours, ready):
    dt = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)
    node = workflow._timegate(dt)
    assert node.ready is ready
    cutoff = dt + timedelta(hours=3, minutes=35)
    assert node.taskname == "UTC > %s" % cutoff.replace(tzinfo=None)


def test_workflow__dt_taskname(cycle):
    assert workflow._dt_taskname(cycle, "foo") == (cycle, "20251001 18Z foo")
    assert workflow._dt_taskname("2025-10-01T18", "foo") == (cycle, "20251001 18Z foo")


def test_workflow__cmd(cycle, cfg, tmp_path):
    obj = Mock(__module__="aigfs.drivers.inference")
    obj.__class__.__name__ = "AIGFSInference"
    expected = (
        f"srun {tmp_path}/bin/run cmd uw execute --module aigfs.drivers.inference "
        f"--classname AIGFSInference --task run --config {cfg} --key-path forecast "
        "--cycle 20251001T18 --leadtime 12"
    )
    assert (
        workflow._cmd(
            obj,
            ["forecast"],
            cycle,
            leadtime=timedelta(hours=12),
            prefix="srun",
        )
        == expected
    )


def test_workflow__execute(capsys, lockkit):
    def run_cmd(*_args, **kwargs):
        kwargs["callback"](Mock(stdout=StringIO("first line\nsecond line\n")))
        output.touch()

    obj, assets, lockfile, output = lockkit
    with patch.object(workflow, "run_shell_cmd", side_effect=run_cmd) as cmd:
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    cmd.assert_called_once_with("/bin/true", callback=ANY, cwd=obj.rundir, taskname=TASKNAME)
    assert lockfile.is_file()
    assert output.is_file()
    assert capsys.readouterr().err == "first line\nsecond line\n"


def test_workflow__execute__ready_elsewhere(logcap, lockkit):
    obj, assets, _, output = lockkit
    output.touch()
    with patch.object(workflow, "run_shell_cmd") as cmd:
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    cmd.assert_not_called()
    assert f"{TASKNAME}: Made ready by another process" in logcap.text


def test_workflow__execute__locked(logcap, lockkit):
    obj, assets, lockfile, output = lockkit
    lockfile.parent.mkdir(parents=True)
    with patch.object(
        workflow, "run_shell_cmd", side_effect=lambda *_a, **_k: output.touch()
    ) as cmd:
        with lockfile.open("w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
            cmd.assert_not_called()
            assert not output.is_file()
            assert f"{TASKNAME}: Running in another process" in logcap.text
        # Lock released by holder, so the command now runs:
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    cmd.assert_called_once_with("/bin/true", callback=ANY, cwd=obj.rundir, taskname=TASKNAME)
    assert output.is_file()


def test_workflow__execute__lock_released(lockkit):
    obj, assets, lockfile, _ = lockkit
    with patch.object(workflow, "run_shell_cmd"):
        workflow._execute("/bin/true", obj.rundir, TASKNAME, assets)
    with lockfile.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # would raise if still held


def test_workflow__fff():
    assert workflow._fff(Path("/path/to/aigfs.t00z.pres.f018.grib2")) == "018"


def test_workflow__passthrough_logger(capsys):
    logger = workflow._passthrough_logger()
    logger.info("some log message")
    assert capsys.readouterr().err.strip() == "some log message"
    assert workflow._passthrough_logger() is logger  # logging module reuses loggers


def test_workflow__schema():
    path = workflow._schema(AIGFSInference)
    assert path.name == "inference.jsonschema"
    assert path.is_file()


def test_workflow__utc():
    dt = datetime(1970, 1, 1)  # noqa: DTZ001
    assert dt.tzinfo is None
    dt = workflow._utc(dt)
    assert dt.tzinfo is UTC
