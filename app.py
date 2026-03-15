from flask import Flask, redirect, render_template, request, session, url_for


app = Flask(__name__)
app.secret_key = "hackathon-demo-secret"


@app.route("/", methods=["GET", "POST"])
def index():
    full_name = ""
    group_number = ""
    direction = ""
    directions = [
        "Программная инженерия",
        "Дизайн",
        "Аналитика",
        "Маркетинг",
        "Менеджмент",
    ]

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        group_number = request.form.get("group_number", "").strip()
        direction = request.form.get("direction", "").strip()
        session["full_name"] = full_name
        session["group_number"] = group_number
        session["direction"] = direction
        return redirect(url_for("success"))

    return render_template(
        "index.html",
        full_name=full_name,
        group_number=group_number,
        direction=direction,
        directions=directions,
    )


@app.route("/success")
def success():
    automats = [
        "Высшая математика",
        "Алгоритмы и структуры данных",
        "Академическое письмо",
        "Английский язык",
    ]
    subjects = [
        {"name": "Программирование", "local_rank": "56/220", "score": "4.5"},
        {"name": "Математический анализ", "local_rank": "41/220", "score": "5.2"},
        {"name": "Дискретная математика", "local_rank": "63/220", "score": "4.8"},
        {"name": "Английский язык", "local_rank": "34/220", "score": "5.4"},
    ]
    selected_index = request.args.get("subject", "1")

    try:
        selected_index = int(selected_index) - 1
    except ValueError:
        selected_index = 0

    if selected_index < 0 or selected_index >= len(subjects):
        selected_index = 0

    return render_template(
        "success.html",
        full_name=session.get("full_name", "Имя Фамилия"),
        automats=automats,
        subjects=subjects,
        selected_subject=subjects[selected_index],
        selected_index=selected_index,
        preliminary_rank="12",
        average_score="5.4",
    )


if __name__ == "__main__":
    app.run(debug=True)
