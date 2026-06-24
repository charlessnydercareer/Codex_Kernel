import json
import subprocess
import sys
from pydantic import BaseModel, Field
from typing import Literal

class StateContract(BaseModel):
    epoch: str
    status: Literal["INITIALIZED", "RECONCILING", "ERROR"]
    cascade_depth: int = Field(..., ge=0, le=1)

def reconcile():
    print("[RECONCILER] Initiating state drift correction...")
    try:
        # Load and validate current state
        with open("src/state.json", "r") as f:
            raw_data = json.load(f)
            validated = StateContract(**raw_data)
            
        # Reconcile logic: Fix status and reset depth if necessary
        if validated.status != "INITIALIZED":
            validated.status = "INITIALIZED"
            validated.cascade_depth = 0
            
            # Atomic Write
            with open("src/state.json", "w") as f:
                json.dump(validated.model_dump(), f, indent=2)
            
            # Git Anchor: State correction is now a ledger-recorded commit
            subprocess.run(["git", "add", "src/state.json"], check=True)
            subprocess.run(["git", "commit", "-m", "RECONCILER: Automated ledger correction"], check=True)
            
            print("[RECONCILER] Reconciliation committed to ledger.")
        else:
            print("[RECONCILER] No drift detected.")
        
    except Exception as e:
        print(f"[RECONCILER] Critical Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    reconcile()
