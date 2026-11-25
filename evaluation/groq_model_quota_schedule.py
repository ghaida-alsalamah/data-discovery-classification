from time import sleep
import httpx
from evaluation import groq_model_holdout as holdout
from evaluation.groq_model_comparison import harness, run_model
from evaluation.score import read
from evaluation.reliability_infer import digest
original=harness.FreeCatalogProvider
class QuotaScheduled(original):
    delay_used=0
    def request(self,*args,**kwargs):
        for retry in range(4):
            try:
                return super().request(*args,**kwargs)
            except httpx.HTTPStatusError as error:
                if error.response.status_code!=429 or retry==3:
                    raise
                try:
                    delay=float(error.response.headers["retry-after"])+2
                except (KeyError,ValueError):
                    raise error
                if not 0 < delay or self.delay_used+delay>300:
                    raise
                self.delay_used+=delay
                self.counters["quota_wait_seconds"]=self.delay_used
                print("Free quota wait", round(delay,1), "seconds", flush=True)
                while delay>0:
                    step=min(50,delay)
                    sleep(step)
                    delay-=step
                self.closed=False

root=holdout.ROOT
seal=read(root/"seal.json")
assert seal["configuration"]==holdout.config()
assert all(digest(root/name)==sha for name,sha in seal["inputs"].items())
harness.FreeCatalogProvider=QuotaScheduled
try:
    sources=[(root,name) for name in holdout.SOURCES]
    run_model("oss120",sources,root/"oss120")
    holdout.participant_probe("oss120")
    holdout.confidence_report(sources,("oss120",))
finally:
    harness.FreeCatalogProvider=original
assert seal["configuration"]==holdout.config()
assert all(digest(root/name)==sha for name,sha in seal["inputs"].items())

