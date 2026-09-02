from app.collectors.ashby import AshbyCollector
from app.collectors.generic import GenericCollector
from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.lever import LeverCollector
from app.collectors.smartrecruiters import SmartRecruitersCollector
from app.collectors.workday import WorkdayCollector

COLLECTORS = {
    "greenhouse": GreenhouseCollector, "lever": LeverCollector, "ashby": AshbyCollector,
    "workday": WorkdayCollector, "smartrecruiters": SmartRecruitersCollector,
    "generic": GenericCollector, "custom": GenericCollector,
}


def get_collector(name: str, http):
    try:
        return COLLECTORS[name](http)
    except KeyError as exc:
        raise ValueError(f"Unsupported ATS: {name}") from exc

