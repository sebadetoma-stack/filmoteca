"""Cliente mínimo de la YouTube Data API v3, con contabilidad de cuota."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/"


def llamar(endpoint, cuota, **params):
    if not cuota.gastar(endpoint):
        return None

    params["key"] = os.environ["YT_API_KEY"]
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")
        if "quotaExceeded" in cuerpo:
            print("  [!] quotaExceeded: Google dice que no queda cuota.")
            return None
        print(f"  [!] HTTP {e.code}: {cuerpo[:250]}")
        return None
    except Exception as e:
        print(f"  [!] Error de red: {e}")
        return None
