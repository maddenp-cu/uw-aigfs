"""
Support for validating AIGFS configurations.
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from pprint import pformat
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from aigfs.common import platforms
from aigfs.strings import STR

# Validation classes


class Partition(BaseModel):
    """
    Model for the `app.platform.partition:` block.
    """

    model_config = ConfigDict(extra="forbid")

    compute: str | None = None
    netaccess: str | None = None
    task: str | None = None

    @model_validator(mode="after")
    def at_least_one(self) -> "Partition":
        model = self.model_dump()
        if not any(model.values()):
            msg = "Specify at least one partition name (%s)" % ", ".join(model.keys())
            raise ValueError(msg)
        return self


class Scheduler(BaseModel):
    """
    Model for the `app.platform.scheduler:` block.
    """

    model_config = ConfigDict(extra="forbid")

    account: str | None = None
    type: Literal["pbs", "slurm"]


class Platform(BaseModel):
    """
    Model for the `app.platform:` block.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    partition: Partition | None = None
    scheduler: Scheduler | None = None

    @field_validator(STR.name)
    @classmethod
    def validate_name(cls, val: str) -> str:
        if val not in platforms():
            msg = "Platform name must be one of: %s" % ", ".join(platforms())
            raise ValueError(msg)
        return val


class Time(BaseModel):
    """
    Model for the `app.time:` block.
    """

    model_config = ConfigDict(extra="forbid")

    fff: str
    hh: str
    m1_hh: str
    m1_yyyymmdd: str
    m2_hh: str
    m2_yyyymmdd: str
    m6h: timedelta
    yyyymmdd: str


class App(BaseModel):
    """
    Model for the `app:` block.
    """

    model_config = ConfigDict(extra="forbid")

    cycle_freq: timedelta | None = None
    first_cycle: datetime | None = None
    home: Path
    last_cycle: datetime | None = None
    modeldir: Path
    platform: Platform
    rundir: Path
    time: Time

    @field_validator("cycle_freq")
    @classmethod
    def validate_cycle_freq(cls, val: timedelta) -> timedelta:
        if val is not None:
            if val.total_seconds() <= 0:
                msg = "cycle_freq must be greater than 0"
                raise ValueError(msg)
            if val.total_seconds() % (6 * 3600) != 0:
                msg = "cycle_freq must be a multiple of 6"
                raise ValueError(msg)
        return val

    @model_validator(mode="after")
    def first_and_last_cycle(self) -> "App":
        if (self.first_cycle is not None) ^ (self.last_cycle is not None):
            msg = "first_cycle and last_cycle must both be defined if either is defined"
            raise ValueError(msg)
        if self.first_cycle is not None and self.last_cycle is not None:
            if self.last_cycle < self.first_cycle:
                msg = "last_cycle cannot precede first_cycle"
                raise ValueError(msg)
            if self.cycle_freq is None:
                msg = "cycle_freq must be defined when first_cycle and last_cycle are defined"
                raise ValueError(msg)
        return self


class Config(BaseModel):
    """
    Model for the overall AIGFS config.
    """

    model_config = ConfigDict(extra="forbid")

    app: App
    ecflow: dict | None = None
    forecast: dict
    post: dict
    prep: dict
    user: dict | None = None
    workflow: dict | None = None

    @model_validator(mode="after")
    def cycle_range_vs_workflow(self) -> "Config":
        workflow = self.ecflow is not None or self.workflow is not None
        cycle_range = (
            self.app.cycle_freq is not None
            and self.app.first_cycle is not None
            and self.app.last_cycle is not None
        )
        if workflow and not cycle_range:
            engine = "ecflow" if self.ecflow is not None else "workflow"
            msg = f"cycle_freq, first_cycle, last_cycle must be defined when {engine} is defined"
            raise ValueError(msg)
        return self


# Public functions


def validate(config: dict[str, object]) -> Config:
    """
    Validate a config.
    """
    try:
        return Config.model_validate(config)
    except ValidationError as e:
        logging.error("Config validation failed:")
        lines = pformat(e.errors()).split("\n")
        for line in lines:
            logging.error(line)
        sys.exit(1)
