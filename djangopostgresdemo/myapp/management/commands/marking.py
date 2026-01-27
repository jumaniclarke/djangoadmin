from django.db import connection
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

def mark_boolean_answer(answertext, solution):
    """Mark a boolean answer (case-insensitive exact match)."""
    return 1 if str(answertext).strip().lower() == str(solution).strip().lower() else 0

def mark_value_answer(answervalue, solution):
    """Mark a value answer (numeric comparison as floats)."""
    try:
        return 1 if float(answervalue) == float(solution) else 0
    except (ValueError, TypeError):
        print(f"ValueError/TypeError in mark_value_answer with answervalue={answervalue}, solution={solution}")
        return 0

def mark_answers_for_session(sessionid):
    """
    For a given sessionid, fetch all answers, compare to solutions in question_md,
    and update the markawarded column in answers.
    """
    print(f"Step 2: Marking actually started with sessionid: {sessionid}")
    print(f"Step 2a: sessionid type = {type(sessionid)}, value = {repr(sessionid)}")
    
    # Force fresh connection state to avoid stale data
    connection.close()
    
    answers = [] #initialize outside the cursor context
    with connection.cursor() as cursor:
        try:
            # Debug: check if data exists for this sessionid
            cursor.execute("SELECT COUNT(*) FROM answers_stream WHERE sessionid = %s", [sessionid])
            count = cursor.fetchone()[0]
            print(f"Step 2b: COUNT(*) for sessionid {sessionid} = {count}")

            cursor.execute(
            "SELECT sessionid, questionid, answertext, answervalue FROM answers_stream WHERE sessionid = %s",
            [sessionid]
            )
            answers = list(cursor.fetchall()) #convert to list immediately, fetchall() returns a list of tuples
            print(f"Step 3: Fetched {len(answers)} answers for sessionid {sessionid}")
        except Exception as e:
            print(f"Database connection failed: {e}")
            return
    # ...existing code...
    print("Reached after fetchall, answers:", answers)  # debug
    if not answers:
        print("answers is empty or exhausted")
        return
    
    for orig_sessionid, questionid, answertext, answervalue in answers:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT question_type, question_sol FROM question_md WHERE question_id = %s",
                [questionid]
            )
            row = cursor.fetchone()
            #print(f"Fetched solution for questionid {questionid}: {row}")
            if not row:
                mark = 0  # or handle missing solution
            else:
                question_type, solution = row
                print(f"Comparing answer '{answertext}' to solution '{solution}'")
                # Mark based on question type
                if question_type == 'boolean':
                    print(f"Marking boolean question for questionid {questionid}")
                    mark = mark_boolean_answer(answertext, solution)
                elif question_type == 'value':
                    print(f"Marking value question for questionid {questionid}, with answervalue {answervalue} and solution {solution}")
                    mark = mark_value_answer(answervalue, solution)
                else:
                    print(f"Unknown question type '{question_type}' for questionid {questionid}")
                    mark = 0

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE answers_stream SET markawarded = %s WHERE sessionid = %s AND questionid = %s",
                [mark, orig_sessionid, questionid]
            )
            print(f"Updated markawarded to {mark} for sessionid {orig_sessionid}, questionid {questionid}")
        
        # Broadcast mark update to WebSocket clients viewing this session
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"session_{orig_sessionid}",
                {
                    "type": "mark_update",
                    "questionid": questionid,
                    "mark": mark
                }
            )
            print(f"Broadcast mark_update for session_{orig_sessionid}, question {questionid}, mark {mark}")
        except Exception as e:
            print(f"Broadcast failed for session_{orig_sessionid}, question {questionid}: {e}")