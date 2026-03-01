from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG HRL =================
CFG = {
    "tps_min": 90,
    "tps_max": 105,
    "lambda_min": 0.75,
    "lambda_max": 1.05,
    "fuel_min_rule": 55.0,   # RÈGLE HRL
    "cheat_delay": 0.3
}

UPLOAD_DIR = "/tmp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= HTML =================
HTML = """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Boat Data Analyzer</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">

<style>
.header-row { height: 120px; }
.logo-box {
  height: 120px;
  display:flex;
  align-items:center;
  justify-content:center;
}
.logo-box img {
  max-height: 90px;
  object-fit: contain;
}
.title-box {
  height: 120px;
  display:flex;
  align-items:center;
  justify-content:center;
}
</style>
</head>

<body class="p-4 bg-dark text-light">
<div class="container">

<div class="row header-row mb-4">
  <div class="col-3 logo-box">
    <img src="{{ url_for('static', filename='p_logo_zoom.png') }}">
  </div>

  <div class="col-6 title-box">
    <h1 class="m-0 text-center">Boat Data Analyzer</h1>
  </div>

  <div class="col-3 logo-box">
    <img src="{{ url_for('static', filename='image_copy.png') }}">
  </div>
</div>

<form method="post" action="/upload" enctype="multipart/form-data">
<div class="row mb-3">
  <div class="col-md-4">
    <input class="form-control" name="boat_id" placeholder="# Embarcation" required>
  </div>
  <div class="col-md-4">
    <input class="form-control" type="date" name="session_date" required>
  </div>
  <div class="col-md-4">
    <input class="form-control" type="time" name="session_time" required>
  </div>
</div>

<input class="form-control mb-3" type="file" name="file" required>
<button class="btn btn-primary">Analyser</button>
</form>

{% if table %}
<hr class="my-4">

<h2 class="text-center {{ 'text-danger' if not pass_test else 'text-success' }}">
  {{ result_message }}
</h2>

<div class="text-center mb-3">
  <strong>Embarcation:</strong> {{ boat_id }} |
  <strong>Date:</strong> {{ session_date }} |
  <strong>Heure:</strong> {{ session_time }}
</div>

<div class="d-flex justify-content-center mb-3">
  <a class="btn btn-success" href="{{ download }}">Télécharger CSV</a>
</div>

<div class="table-responsive">
  {{ table|safe }}
</div>

{% endif %}

</div>
</body>
</html>
"""

# ================= LECTURE ROBUSTE =================
def load_link_csv(file):
    raw = pd.read_csv(file, header=None, engine="python", on_bad_lines="skip")

    if len(raw) < 25:
        raise ValueError("Fichier incomplet")

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()
    df.columns = header
    df = df.loc[:, ~df.columns.astype(str).str.match(r'^\d+$')]  # supprime colonne "19"

    return df.reset_index(drop=True)

# ================= ANALYSE =================
def analyze_dataframe(df):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["Lambda_raw"] = pd.to_numeric(df.get("Lambda 1"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")

    df = df.dropna(subset=["Time", "TPS", "Lambda_raw", "Fuel"])

    df["Lambda"] = df["Lambda_raw"] / 14.7

    # ================= RÈGLES HRL =================

    df["OUT_TPS"] = ~df["TPS"].between(CFG["tps_min"], CFG["tps_max"])
    df["OUT_Lambda"] = ~df["Lambda"].between(CFG["lambda_min"], CFG["lambda_max"])

    # RÈGLE OFFICIELLE
    df["OUT_Fuel"] = df["Fuel"] < CFG["fuel_min_rule"]

    df["OUT"] = df["OUT_TPS"] | df["OUT_Lambda"] | df["OUT_Fuel"]

    df["dt"] = df["Time"].diff().fillna(0)

    cumul = 0
    fail_time = None

    for t, out, dt in zip(df["Time"], df["OUT"], df["dt"]):
        if out:
            cumul += dt
            if cumul >= CFG["cheat_delay"]:
                fail_time = t
                break
        else:
            cumul = 0

    pass_test = fail_time is None

    return df, pass_test, fail_time

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(HTML, table=None)

@app.route("/upload", methods=["POST"])
def upload():
    try:
        file = request.files["file"]

        boat_id = request.form["boat_id"]
        session_date = request.form["session_date"]
        session_time = request.form["session_time"]

        df = load_link_csv(file)
        df, pass_test, fail_time = analyze_dataframe(df)

        if pass_test:
            message = "PASS – Datalog compliant with HRL rules"
        else:
            message = f"Datalog NOT compliant with rules – Fail at {fail_time:.2f}s"

        fname = f"result_{datetime.now().timestamp()}.csv"
        path = os.path.join(UPLOAD_DIR, fname)
        df.to_csv(path, index=False)

        table = df.head(150).to_html(
            classes="table table-dark table-striped",
            index=False
        )

        return render_template_string(
            HTML,
            table=table,
            download=url_for("download", fname=fname),
            result_message=message,
            pass_test=pass_test,
            boat_id=boat_id,
            session_date=session_date,
            session_time=session_time
        )

    except Exception as e:
        return f"Erreur : {str(e)}"

@app.route("/download")
def download():
    return send_file(os.path.join(UPLOAD_DIR, request.args["fname"]), as_attachment=True)

# ================= RENDER =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
