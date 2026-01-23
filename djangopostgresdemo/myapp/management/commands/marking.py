from django.db import connection

def mark_answers_for_session(sessionid):
    """
    For a given sessionid, fetch all answers, compare to solutions in question_md,
    and update the markawarded column in answers.
    """
    print(f"Step 2: Marking actually started with sessionid: {sessionid}")
    with connection.cursor() as cursor:
        try:
            cursor.execute(
            "SELECT sessionid, questionid, answertext FROM answers_stream WHERE sessionid = %s",
            [sessionid]
            )
            answers = cursor.fetchall()
            print(f"Fetched {len(answers)} answers for sessionid {sessionid}")
        except Exception as e:
            print(f"Database connection failed: {e}")
            return
        
    for sessionid, questionid, answertext in answers:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT question_sol FROM question_md WHERE question_id = %s",
                [questionid]
            )
            row = cursor.fetchone()
            if not row:
                mark = 0  # or handle missing solution
            else:
                solution = row[0]
                # Simple marking: exact match
                mark = 1 if str(answertext).strip() == str(solution).strip() else 0

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE answers_stream SET markawarded = %s WHERE sessionid = %s AND questionid = %s",
                [mark, sessionid, questionid]
            )
