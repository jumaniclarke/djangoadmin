from django.db import connection
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import re

def mark_boolean_answer(answertext, solution):
    """Mark a boolean answer (case-insensitive exact match)."""
    return 1 if str(answertext).strip().lower() == str(solution).strip().lower() else 0

def mark_value_answer(answervalue, solution, cursor, question_mdid):
    """Mark a value answer with tolerance range from question_value_rule."""
    try:
        answer_float = float(answervalue)
        solution_float = float(solution)
        
        # Fetch tolerance value from question_value_rule
        cursor.execute(
            "SELECT tol_value FROM question_value_rule WHERE question_mdid = %s",
            [question_mdid]
        )
        tol_row = cursor.fetchone()
        
        if not tol_row:
            # No tolerance rule found, do exact match
            return 1 if answer_float == solution_float else 0
        # get tolerance as percent
        tol_percent = float(tol_row[0]) / 100.0  # Convert percent to decimal
        tolerance = solution_float * tol_percent
        lower_bound = solution_float - tolerance
        upper_bound = solution_float + tolerance
        
        return 1 if lower_bound <= answer_float <= upper_bound else 0
    except (ValueError, TypeError) as e:
        print(f"ValueError/TypeError in mark_value_answer with answervalue={answervalue}, solution={solution}: {e}")
        return 0

def _split_formula_args(arg_text):
    if arg_text is None:
        return []
    args = []
    current = []
    depth = 0
    for ch in arg_text:
        if ch == ',' and depth == 0:
            args.append(''.join(current).strip())
            current = []
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(depth - 1, 0)
        current.append(ch)
    if current:
        args.append(''.join(current).strip())
    return args

def _normalize_formula_text(text, case_insensitive=False, ignore_whitespace=False):
    """
    Normalize formula text for comparison by optionally removing whitespace and converting to lowercase.
    
    Args:
        text: The formula text to normalize (can be None or any type convertible to string)
        case_insensitive: If True, convert text to lowercase for case-insensitive comparison
        ignore_whitespace: If True, remove all whitespace from the text
    
    Returns:
        Normalized string, or empty string if text is None
    """
    # Handle None values by returning empty string
    if text is None:
        return ''
    
    # Convert input to string
    value = str(text)
    
    # Remove all whitespace if requested (useful for comparing formulas with different spacing)
    if ignore_whitespace:
        value = re.sub(r"\s+", "", value)
    
    # Convert to lowercase if requested (useful for case-insensitive function name comparison)
    if case_insensitive:
        value = value.lower()
    
    return value

def mark_formula_answer(answerformula, cursor, question_mdid):
    """Mark a function/formula answer based on question_formula_rule and question_formula_arg.
    
    Returns:
        tuple: (mark, feedback) where mark is int and feedback is str
    """
    print(f"Marking formula answer: {answerformula} for question_mdid: {question_mdid}")
    feedback_parts = []
    
    if not answerformula:
        print("No answer formula provided")
        return 0, "No formula provided."

    cursor.execute(
        """
        SELECT rule_id, function_name, arg_count, match_policy, case_insensitive, ignore_whitespace
        FROM question_formula_rule
        WHERE question_mdid = %s AND is_active = TRUE
        ORDER BY rule_id ASC
        LIMIT 1
        """,
        [question_mdid]
    )
    rule_row = cursor.fetchone()
    if not rule_row:
        print(f"No active formula rule found for question_mdid: {question_mdid}")
        return 0, "No formula rule found for this question."

    rule_id, function_name, arg_count, match_policy, case_insensitive, ignore_whitespace = rule_row
    print(f"Using formula rule_id: {rule_id}, function_name: {function_name}, arg_count: {arg_count}, match_policy: {match_policy}, case_insensitive: {case_insensitive}, ignore_whitespace: {ignore_whitespace}")

    raw = str(answerformula).strip()
    if raw.startswith('='):
        raw = raw[1:]

    if '(' in raw and raw.endswith(')'):
        func_name, arg_text = raw.split('(', 1)
        arg_text = arg_text[:-1]
    else:
        func_name = raw
        arg_text = ''

    func_name_norm = _normalize_formula_text(func_name, case_insensitive, ignore_whitespace)
    expected_func_norm = _normalize_formula_text(function_name, case_insensitive, ignore_whitespace)
    print(f"Comparing function name '{func_name_norm}' to expected '{expected_func_norm}'")
    
    if func_name_norm == expected_func_norm:
        mark = 1
        feedback_parts.append(f"✓ Function name '{func_name}' matches the expected function '{function_name}'.")
    else:
        mark = 0
        feedback_parts.append(f"✗ Function name '{func_name}' does not match the expected function '{function_name}'.")

    answer_args = _split_formula_args(arg_text)

    cursor.execute(
        """
        SELECT position, arg_kind, is_optional, expected_sheet, expected_ref_a1, expected_ref_end_a1,
               expected_number, expected_text, expected_boolean, expected_function, expected_expr_norm,
               expected_any_of, compare_mode, regex_text, ref_style, allow_named_range, allow_external_ref,
               allowed_sheet, min_number, max_number
        FROM question_formula_arg
        WHERE rule_id = %s
        ORDER BY position ASC
        """,
        [rule_id]
    )
    expected_args = cursor.fetchall()

    for idx, expected in enumerate(expected_args):
        (
            position, arg_kind, is_optional, expected_sheet, expected_ref_a1, expected_ref_end_a1,
            expected_number, expected_text, expected_boolean, expected_function, expected_expr_norm,
            expected_any_of, compare_mode, regex_text, ref_style, allow_named_range, allow_external_ref,
            allowed_sheet, min_number, max_number
        ) = expected

        if idx >= len(answer_args):
            if not is_optional:
                feedback_parts.append(f"\n✗ Argument {position} is missing (required).")
                continue
            else:
                feedback_parts.append(f"\n⊘ Argument {position} is missing (optional).")
                continue

        answer_arg = answer_args[idx]
        answer_arg_norm = _normalize_formula_text(answer_arg, case_insensitive, ignore_whitespace)

        expected_values = []

        if expected_ref_a1:
            if expected_ref_end_a1:
                expected_range = f"{expected_ref_a1}:{expected_ref_end_a1}"
            else:
                expected_range = expected_ref_a1
            if expected_sheet:
                expected_range = f"{expected_sheet}!{expected_range}"
            expected_values.append(expected_range)

        if expected_text is not None:
            expected_values.append(str(expected_text))

        if expected_number is not None:
            expected_values.append(str(expected_number))

        if expected_boolean is not None:
            expected_values.append("TRUE" if expected_boolean else "FALSE")

        if expected_function:
            expected_values.append(str(expected_function))

        if expected_expr_norm:
            expected_values.append(str(expected_expr_norm))

        if expected_any_of:
            for token in re.split(r"[|,]", str(expected_any_of)):
                token = token.strip()
                if token:
                    expected_values.append(token)

        arg_matched = False

        if regex_text:
            if re.fullmatch(regex_text, answer_arg.strip()):
                mark += 1
                feedback_parts.append(f"\n✓ Argument: {position} '{answer_arg}' matches the regex pattern.")
                print(f"Regex match for argument '{answer_arg}' with pattern '{regex_text}'")
                continue

        matched = False
        for expected_value in expected_values:
            expected_norm = _normalize_formula_text(expected_value, case_insensitive, ignore_whitespace)
            if expected_norm == answer_arg_norm:
                matched = True
                arg_matched = True
                break

        if matched:
            mark += 1
            feedback_parts.append(f"\n✓ Argument: {position} '{answer_arg}' matches the expected value.")
        else:
            expected_str = ", ".join(expected_values) if expected_values else "unknown"
            feedback_parts.append(f"\n✗ Argument: {position} '{answer_arg}' does not match. Expected: {expected_str}")

    feedback = " ".join(feedback_parts)
    return mark, feedback

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
            "SELECT sessionid, questionid, answertext, answervalue, answerformula FROM answers_stream WHERE sessionid = %s",
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
    
    for orig_sessionid, questionid, answertext, answervalue, answerformula in answers:
        feedback = None
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT question_mdid, question_type, question_sol FROM question_md WHERE question_id = %s",
                [questionid]
            )
            row = cursor.fetchone()

            if not row:
                mark = 0  # or handle missing solution
                feedback = "No solution found."
            else:
                question_mdid, question_type, solution = row
                print(f"Comparing answer '{answertext}' to solution '{solution}'")
                # Mark based on question type
                if question_type == 'boolean':
                    print(f"Marking boolean question for questionid {questionid}")
                    mark = mark_boolean_answer(answertext, solution)
                    feedback = "Correct." if mark else "Incorrect."
                elif question_type == 'value':
                    print(f"Marking value question for questionid {questionid}, with answervalue {answervalue} and solution {solution}")
                    mark = mark_value_answer(answervalue, solution, cursor, question_mdid)
                    feedback = "Correct." if mark else "Incorrect."
                elif question_type == 'formula':
                    print(f"Marking formula question for questionid {questionid}, with formula {answerformula}")
                    mark, feedback = mark_formula_answer(answerformula, cursor, question_mdid)
                else:
                    print(f"Unknown question type '{question_type}' for questionid {questionid}")
                    mark = 0
                    feedback = "Unknown question type."

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE answers_stream SET markawarded = %s, feedback = %s WHERE sessionid = %s AND questionid = %s",
                [mark, feedback, orig_sessionid, questionid]
            )
            print(f"Updated markawarded to {mark} and feedback to '{feedback}' for sessionid {orig_sessionid}, questionid {questionid}")
        
        # Broadcast mark update to WebSocket clients viewing this session
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"session_{orig_sessionid}",
                {
                    "type": "mark_update",
                    "questionid": questionid,
                    "mark": mark,
                    "feedback": feedback
                }
            )
            print(f"Broadcast mark_update for session_{orig_sessionid}, question {questionid}, mark {mark}, feedback '{feedback}'")
        except Exception as e:
            print(f"Broadcast failed for session_{orig_sessionid}, question {questionid}: {e}")