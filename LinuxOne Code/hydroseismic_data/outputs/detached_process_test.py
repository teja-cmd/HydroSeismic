import json, time
from datetime import datetime, timezone
from pathlib import Path
target = Path('/home/ibm-user/hydroseismic_data/outputs/detached_process_test_result.json')
time.sleep(5)
target.write_text(json.dumps({'status': 'COMPLETED', 'written_at_utc': datetime.now(timezone.utc).isoformat()}) + '\n')
