from flask import Flask, render_template, request, redirect, url_for, Response, session
import os, csv, io
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set.")
    return psycopg2.connect(DATABASE_URL)

def create_tables():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY, usn TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
        semester INTEGER NOT NULL, section TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS subjects (
        id SERIAL PRIMARY KEY, subject_code TEXT UNIQUE, subject_name TEXT UNIQUE NOT NULL,
        semester INTEGER NOT NULL, section TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS marks (
        id SERIAL PRIMARY KEY,
        student_id INTEGER REFERENCES students(id) ON DELETE CASCADE,
        subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
        subject TEXT NOT NULL, test_name TEXT, test_date DATE,
        max_marks NUMERIC, marks_obtained NUMERIC NOT NULL)""")
    # Make the newer optional fields safe when an older marks table already exists.
    cur.execute("ALTER TABLE marks ALTER COLUMN test_name DROP NOT NULL")
    cur.execute("ALTER TABLE marks ALTER COLUMN max_marks DROP NOT NULL")
    conn.commit()
    cur.close(); conn.close()

if DATABASE_URL:
    create_tables()

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/students", methods=["GET","POST"])
def students():
    if request.method == "POST":
        conn=get_db(); cur=conn.cursor()
        try:
            cur.execute("INSERT INTO students (usn,name,semester,section) VALUES (%s,%s,%s,%s)",
                        (request.form["usn"].strip(), request.form["name"].strip(),
                         int(request.form["semester"]), request.form["section"].upper()))
            conn.commit()
        except Exception as e:
            conn.rollback(); cur.close(); conn.close()
            return f"Could not add student: {e}",400
        cur.close(); conn.close()
        return redirect(url_for("students"))
    conn=get_db(); cur=conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM students ORDER BY semester,section,usn")
    rows=cur.fetchall(); cur.close(); conn.close()
    return render_template("students.html", students=rows)

@app.route("/bulk-upload", methods=["GET","POST"])
def bulk_upload():
    result=None; errors=[]
    if request.method=="POST":
        file=request.files.get("file")
        if not file or not file.filename:
            errors.append("Please select a CSV file.")
        elif not file.filename.lower().endswith(".csv"):
            errors.append("Please upload a CSV file.")
        else:
            try:
                reader=csv.DictReader(io.StringIO(file.read().decode("utf-8-sig")))
                required={"USN","Student Name","Semester","Section"}
                headers={h.strip() for h in (reader.fieldnames or [])}
                if not required.issubset(headers):
                    errors.append("Headers must be: USN, Student Name, Semester, Section")
                else:
                    conn=get_db(); cur=conn.cursor(); added=0
                    for line_no, raw in enumerate(reader,start=2):
                        row={k.strip():(v or "").strip() for k,v in raw.items() if k}
                        try:
                            usn=row.get("USN",""); name=row.get("Student Name","")
                            sem=int(row.get("Semester","")); section=row.get("Section","").upper()
                            if not usn or not name: raise ValueError("USN and Student Name are required")
                            if sem<1 or sem>8: raise ValueError("Semester must be 1 to 8")
                            if section not in "ABCDEF": raise ValueError("Section must be A to F")
                            cur.execute("INSERT INTO students (usn,name,semester,section) VALUES (%s,%s,%s,%s)",
                                        (usn,name,sem,section)); added+=1
                        except Exception as e:
                            conn.rollback(); errors.append(f"Row {line_no}: {e}")
                    conn.commit(); cur.close(); conn.close()
                    result=f"{added} student(s) uploaded successfully."
            except Exception as e: errors.append(str(e))
    return render_template("bulk_upload.html",result=result,errors=errors)

@app.route("/download-sample")
def download_sample():
    data="USN,Student Name,Semester,Section\n1AB23AI001,Rahul Kumar,3,A\n1AB23AI002,Priya Sharma,3,A\n"
    return Response(data,mimetype="text/csv",
        headers={"Content-Disposition":"attachment; filename=students_sample.csv"})

@app.route("/subjects", methods=["GET","POST"])
def subjects():
    if request.method=="POST":
        conn=get_db(); cur=conn.cursor()
        try:
            code=request.form.get("subject_code","").strip() or None
            name=request.form["subject_name"].strip()
            sem=int(request.form["semester"])
            section=request.form["section"].upper()
            cur.execute("INSERT INTO subjects(subject_code,subject_name,semester,section) VALUES(%s,%s,%s,%s)",
                        (code,name,sem,section))
            conn.commit()
        except Exception as e:
            conn.rollback(); cur.close(); conn.close()
            return f"Could not add subject: {e}",400
        cur.close(); conn.close()
        return redirect(url_for("subjects"))
    conn=get_db(); cur=conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM subjects ORDER BY semester,section,subject_name")
    rows=cur.fetchall(); cur.close(); conn.close()
    return render_template("subjects.html",subjects=rows)

@app.route("/marks", methods=["GET","POST"])
def marks():
    conn=get_db()
    cur=conn.cursor(cursor_factory=RealDictCursor)
    if request.method=="POST":
        try:
            student_id=int(request.form["student_id"])
            subject_id=int(request.form["subject_id"])
            obtained=float(request.form["marks_obtained"])
            test_name=request.form.get("test_name","").strip() or None
            test_date=request.form.get("test_date") or None
            max_marks=float(request.form["max_marks"]) if request.form.get("max_marks") else None
            semester=request.form.get("semester", "")
            section=request.form.get("section", "")
            cur.execute("SELECT subject_name FROM subjects WHERE id=%s",(subject_id,))
            sub=cur.fetchone()
            if not sub: raise ValueError("Invalid subject")
            cur.execute("""INSERT INTO marks(student_id,subject_id,subject,test_name,test_date,max_marks,marks_obtained)
                           VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                        (student_id,subject_id,sub["subject_name"],test_name,test_date,max_marks,obtained))
            conn.commit()
            # Remember the selected semester and section for the next marks entry.
            session["marks_semester"] = semester
            session["marks_section"] = section
            cur.close(); conn.close()
            return redirect(url_for("marks"))
        except Exception as e:
            conn.rollback()
            cur.close(); conn.close()
            return f"Could not save marks: {e}",400

    # Reuse the last selected semester/section unless the user explicitly changes it.
    semester=request.args.get("semester")
    section=request.args.get("section")
    if semester is None:
        semester=session.get("marks_semester", "")
    else:
        session["marks_semester"]=semester
    if section is None:
        section=session.get("marks_section", "")
    else:
        session["marks_section"]=section

    students=[]
    subjects=[]
    if semester and section:
        cur.execute("SELECT * FROM students WHERE semester=%s AND section=%s ORDER BY usn",
                    (semester,section))
        students=cur.fetchall()
        cur.execute("SELECT * FROM subjects WHERE semester=%s AND section=%s ORDER BY subject_name",
                    (semester,section))
        subjects=cur.fetchall()
    cur.close(); conn.close()
    return render_template("marks.html",students=students,subjects=subjects,
                           semester=semester,section=section)

@app.route("/report")
def report():
    from datetime import date
    from collections import OrderedDict

    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")
    semester = request.args.get("semester", "")
    section = request.args.get("section", "")
    subject = request.args.get("subject", "")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Populate the report subject dropdown from configured subjects.
    if semester and section:
        cur.execute("SELECT DISTINCT subject_name FROM subjects WHERE semester=%s AND section=%s ORDER BY subject_name", (semester, section))
    elif semester:
        cur.execute("SELECT DISTINCT subject_name FROM subjects WHERE semester=%s ORDER BY subject_name", (semester,))
    elif section:
        cur.execute("SELECT DISTINCT subject_name FROM subjects WHERE section=%s ORDER BY subject_name", (section,))
    else:
        cur.execute("SELECT DISTINCT subject_name FROM subjects ORDER BY subject_name")
    subject_options = [r["subject_name"] for r in cur.fetchall()]

    q = """SELECT s.usn, s.name, s.semester, s.section,
                  m.subject, m.test_date, m.marks_obtained
           FROM students s
           JOIN marks m ON s.id=m.student_id
           WHERE m.test_date IS NOT NULL"""
    params = []

    if from_date:
        q += " AND m.test_date >= %s"
        params.append(from_date)
    if to_date:
        q += " AND m.test_date <= %s"
        params.append(to_date)
    if semester:
        q += " AND s.semester=%s"
        params.append(semester)
    if section:
        q += " AND s.section=%s"
        params.append(section)
    if subject:
        q += " AND m.subject ILIKE %s"
        params.append("%" + subject + "%")

    q += " ORDER BY s.semester,s.section,s.usn,m.test_date,m.subject"
    cur.execute(q, params)
    rows = cur.fetchall()

    # One row per USN. Each date becomes a column.
    date_list = sorted({r["test_date"].isoformat() for r in rows if r["test_date"]})
    grouped = OrderedDict()

    for r in rows:
        key = r["usn"]
        if key not in grouped:
            grouped[key] = {
                "usn": r["usn"],
                "name": r["name"],
                "semester": r["semester"],
                "section": r["section"],
                "dates": {}
            }
        d = r["test_date"].isoformat()
        # If more than one mark exists for the same USN/date, show all marks.
        old = grouped[key]["dates"].get(d)
        value = str(r["marks_obtained"])
        grouped[key]["dates"][d] = value if not old else old + " / " + value

    report_rows = list(grouped.values())
    cur.close()
    conn.close()

    return render_template(
        "report.html",
        rows=report_rows,
        dates=date_list,
        from_date=from_date,
        to_date=to_date,
        semester=semester,
        section=section,
        subject=subject,
        subject_options=subject_options
    )

if __name__=="__main__":
    app.run(debug=True,host="0.0.0.0",port=5000)
