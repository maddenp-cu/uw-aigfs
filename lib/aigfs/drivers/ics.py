import logging
import re
from collections.abc import Iterator
from functools import cached_property
from pathlib import Path

import xarray as xr
from iotaa import Asset, collection, external, task
from uwtools.api.config import get_yaml_config
from uwtools.api.driver import DriverCycleBased, FileStager
from uwtools.api.utils import atomic, run_shell_cmd

from aigfs.strings import STR


class AIGFSICs(DriverCycleBased, FileStager):
    """
    A driver for generating AIGFS initial conditions.
    """

    # Public tasks

    @task
    def merged_netcdf_files(self) -> Iterator:
        """
        A netCDF file comprising multiple processed intermediate netCDF files.
        """
        path = self.output["ics"]
        yield f"Merged netCDF file {path}"
        yield Asset(path, path.is_file)
        reqs = self.ncfiles()
        yield reqs
        datasets = map(xr.open_dataset, reqs.ref)
        ds = xr.merge(datasets, compat="no_conflicts", join="outer")
        ds = ds.drop_dims(STR.level)
        ds = ds.rename(
            {
                STR.APCP_surface: STR.total_precipitation_6hr,
                STR.HGT: STR.geopotential,
                STR.HGT_surface: STR.geopotential_at_surface,
                STR.LAND_surface: STR.land_sea_mask,
                STR.PRMSL_meansealevel: STR.mean_sea_level_pressure,
                STR.SPFH: STR.specific_humidity,
                STR.TMP: STR.temperature,
                STR.TMP_2maboveground: STR.two_m_temperature,
                STR.UGRD: STR.u_component_of_wind,
                STR.UGRD_10maboveground: STR.ten_m_u_component_of_wind,
                STR.VGRD: STR.v_component_of_wind,
                STR.VGRD_10maboveground: STR.ten_m_v_component_of_wind,
                STR.VVEL: STR.vertical_velocity,
                STR.latitude: STR.lat,
                STR.longitude: STR.lon,
                STR.plevel: STR.level,
            }
        )
        ds = ds.assign_coords(datetime=ds.time)
        ds[STR.lat] = ds[STR.lat].astype("float32")
        ds[STR.lon] = ds[STR.lon].astype("float32")
        ds[STR.level] = ds[STR.level].astype("int32")
        ds[STR.time] = ds[STR.time] - ds.time[0]  # time now relative to the first time step
        ds = ds.expand_dims(dim=STR.batch)
        ds[STR.datetime] = ds[STR.datetime].expand_dims(dim=STR.batch)
        sfc_geop = ds[STR.geopotential_at_surface].squeeze(STR.batch)
        sfc_geop = (
            sfc_geop.isel(time=1) if sfc_geop.isel(time=0).isnull().all() else sfc_geop.isel(time=0)
        )
        ds[STR.geopotential_at_surface] = sfc_geop
        ls_mask = ds[STR.land_sea_mask].squeeze(STR.batch)
        ls_mask = (
            ls_mask.isel(time=0) if ls_mask.isel(time=1).isnull().all() else ls_mask.isel(time=1)
        )
        ds[STR.land_sea_mask] = ls_mask
        # Update geopotential unit to m2/s2 by multiplying 9.80665.
        ds[STR.geopotential_at_surface] = ds[STR.geopotential_at_surface] * 9.80665
        ds[STR.geopotential] = ds[STR.geopotential] * 9.80665
        # Update total_precipitation_6hr unit to (m) from (kg/m^2) by dividing it by 1000kg/m³.
        ds[STR.total_precipitation_6hr] = ds[STR.total_precipitation_6hr] / 1000
        ds.to_netcdf(path)

    @collection
    def ncfiles(self) -> Iterator:
        """
        netCDF files comprising extracted GRIB variables at various levels.
        """
        yield "netCDF files from GRIB inputs"
        if (paths_cmds := self._ncfiles_to_cmds) is None:
            yield self._no_ncfiles()
        else:
            yield [self._ncfile(path, cmd) for path, cmd in paths_cmds.items()]

    @collection
    def provisioned_rundir(self) -> Iterator:
        """
        Run directory provisioned with all required content.
        """
        yield self.taskname("provisioned run directory")
        yield None

    @collection
    def run(self) -> Iterator:
        """
        An AIGFSICs run.
        """
        yield "AIGFSICs run"
        yield self.merged_netcdf_files()

    # Private tasks

    @task
    def _ncfile(self, path: Path, cmd: str) -> Iterator:
        taskname = f"netCDF file {path}"
        yield taskname
        yield Asset(path, path.is_file)
        yield [self.files_copied(), self.files_hardlinked(), self.files_linked()]
        with atomic(path) as tmp:
            run_shell_cmd(cmd=cmd.format(ncfile=tmp), cwd=self.rundir, taskname=taskname)

    @external
    def _no_ncfiles(self) -> Iterator:
        yield "Missing netCDF files"
        yield Asset(None, lambda: False)

    # Public helper methods

    @classmethod
    def driver_name(cls) -> str:
        """
        Returns the name of this driver.
        """
        return STR.aigfs_ics

    @property
    def output(self) -> dict[str, Path]:
        return {"ics": self.rundir / f"aigfs.t{self.cycle.strftime('%H')}z.ic.nc"}

    # Private helper methods

    @cached_property
    def _ncfiles_to_cmds(self) -> dict[Path, str] | None:
        """
        A mapping from netCDF file paths to the commands that create them.
        """
        datadir = self.rundir / STR.data
        paths = [
            self.rundir / dst
            for section in (STR.files_to_copy, STR.files_to_hardlink, STR.files_to_link)
            for dst in self.config.get(section, [])
            if Path(dst).parts[0] == datadir.name
        ]
        paths = sorted(set(paths), reverse=True)
        mapping: dict[Path, str] = {}
        for suffix, cfgs in get_yaml_config(self.config[STR.grib_in_config]).items():
            for var, cfg in cfgs.items():
                lev = cfg[STR.levels][0]
                for path in filter(lambda x: x.name.endswith(suffix), paths):
                    if (load_once := cfg.get(STR.load_once)) is False:
                        continue
                    logging.debug("Loading %s", var)
                    if not (m := re.match(rf"^.*\.t(\d\d)z{suffix}$", path.name)):
                        msg = "GRIB files don't have names expected by this driver!"
                        logging.error(msg)
                        return None
                    if load_once is True:
                        cfg[STR.load_once] = False
                    fmt = lambda x: re.sub(r"[|()]", ".", x).replace(":", "")
                    ncfile = datadir / "{var}_{lev}_{hh}{suffix}.nc".format(
                        var=fmt(var),
                        lev=fmt(lev).replace(" ", "_"),
                        hh=m.groups()[0],
                        suffix=suffix,
                    )
                    form = "wgrib2 -match '%s' -match '%s' -nc_nlev %s -netcdf {ncfile} %s"
                    mapping[ncfile] = form % (lev, var, lev.count("|") + 1, path)
        return mapping
