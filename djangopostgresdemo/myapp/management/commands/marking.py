from django.db import connection
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import re
import spacy
from .pandas_automation import get_base

def mark_boolean_answer(answertext, solution):
    """Mark a boolean answer (case-insensitive exact match)."""
    return 1 if str(answertext).strip().lower() == str(solution).strip().lower() else 0

def mark_value_answer(answervalue, solution, cursor, question_md_id):
    """Mark a value answer with tolerance range from question_value_rule."""
    try:
        answer_float = float(answervalue)
        solution_float = float(solution)
        
        # Fetch tolerance value from question_value_rule
        cursor.execute(
            "SELECT tol_value FROM question_value_rule WHERE question_md_id = %s",
            [question_md_id]
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

def mark_formula_answer(answerformula, cursor, question_md_id):
    """Mark a function/formula answer based on question_formula_rule and question_formula_arg.
    
    Returns:
        tuple: (mark, feedback) where mark is int and feedback is str
    """
    print(f"Marking formula answer: {answerformula} for question_md_id: {question_md_id}")
    feedback_parts = []
    
    if not answerformula:
        print("No answer formula provided")
        return 0, "No formula provided."

    cursor.execute(
        """
        SELECT rule_id, function_name, arg_count, match_policy, case_insensitive, ignore_whitespace
        FROM question_formula_rule
        WHERE question_md_id = %s AND is_active = TRUE
        ORDER BY rule_id ASC
        LIMIT 1
        """,
        [question_md_id]
    )
    rule_row = cursor.fetchone()
    if not rule_row:
        print(f"No active formula rule found for question_md_id: {question_md_id}")
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
                feedback_parts.append(f"\n✓ Argument {position}: '{answer_arg}' matches the regex pattern.")
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
            feedback_parts.append(f"\n✓ Argument {position}: '{answer_arg}' matches the expected value.")
        else:
            expected_str = ", ".join(expected_values) if expected_values else "unknown"
            feedback_parts.append(f"\n✗ Argument {position}: '{answer_arg}' does not match. Expected: {expected_str}")

    feedback = " ".join(feedback_parts)
    return mark, feedback

def _extract_root_nouns(phrase_text):
    """
    Extract all root nouns from a phrase using spaCy.
    
    Args:
        phrase_text: String containing the phrase
        
    Returns:
        List of root noun texts. Returns empty list if no root nouns found.
    """
    nlp = spacy.load("en_core_web_trf")
    doc = nlp(phrase_text)
    root_nouns = []
    
    for token in doc:
        if token.pos_ == 'NOUN' and (token.dep_ == 'ROOT' or token.head == token):
            root_nouns.append(token.text)
    
    return root_nouns

def mark_nlp_answer(answertext, cursor, question_md_id):
    """Mark an NLP answer by comparing root nouns with expected phrase variants.
    
    Logic:
    1. Fetch the active NLP rule for the question
    2. Fetch all phrase variants for that rule
    3. For each variant, extract base form using get_base() and extract root nouns
    4. Extract base form and root nouns from student's answer
    5. Compare: if student's root noun matches any expected root noun, award 2 marks
    6. If match: feedback says "correct"
    7. If no match: feedback says "your base is different from the expected base" and lists expected bases
    
    Returns:
        tuple: (mark, feedback) where mark is int and feedback is str
    """
    print(f"Marking NLP answer: {answertext} for question_md_id: {question_md_id}")
    
    if not answertext:
        print("No answer text provided")
        return 0, "No answer provided."
    
    # Fetch the active NLP rule for this question
    cursor.execute(
        """
        SELECT question_nlp_rule_id, language, spacy_model
        FROM question_nlp_rule
        WHERE question_md_id = %s AND is_active = TRUE
        ORDER BY question_nlp_rule_id ASC
        LIMIT 1
        """,
        [question_md_id]
    )
    rule_row = cursor.fetchone()
    
    if not rule_row:
        print(f"No active NLP rule found for question_md_id: {question_md_id}")
        return 0, "No NLP rule found for this question."
    
    question_nlp_rule_id, language, spacy_model = rule_row
    print(f"Using NLP rule_id: {question_nlp_rule_id}, language: {language}, spacy_model: {spacy_model}")
    
    # Fetch all active phrase variants for this rule
    cursor.execute(
        """
        SELECT phrase_variant_id, phrase_text
        FROM question_nlp_phrase_variant
        WHERE question_nlp_rule_id = %s AND active = TRUE
        ORDER BY variant_rank ASC
        """,
        [question_nlp_rule_id]
    )
    phrase_variants = cursor.fetchall()
    
    if not phrase_variants:
        print(f"No active phrase variants found for rule_id: {question_nlp_rule_id}")
        return 0, "No phrase variants found for this question."
    
    # Extract base and root nouns from student's answer
    try:
        student_base = get_base(answertext.strip())
        print(f"Student base: {student_base}")
        student_root_nouns = _extract_root_nouns(student_base)
        print(f"Student root nouns: {student_root_nouns}")
        
        # Only proceed if student has exactly one root noun
        if len(student_root_nouns) != 1:
            return 0, f"Your answer has {len(student_root_nouns)} root noun(s). Expected exactly 1."
        
        student_root_noun = student_root_nouns[0].lower()
    except Exception as e:
        print(f"Error extracting base from student answer: {e}")
        return 0, f"Error processing your answer: {str(e)}"
    
    # Extract base and root nouns from each expected phrase variant
    expected_bases = []
    expected_root_nouns = []
    
    for variant_id, phrase_text in phrase_variants:
        try:
            expected_base = get_base(phrase_text.strip())
            print(f"Expected base for variant {variant_id}: {expected_base}")
            expected_bases.append(expected_base)
            
            variant_root_nouns = _extract_root_nouns(expected_base)
            print(f"Expected root nouns for variant {variant_id}: {variant_root_nouns}")
            
            # Only accept variants with exactly one root noun
            if len(variant_root_nouns) == 1:
                expected_root_nouns.append(variant_root_nouns[0].lower())
        except Exception as e:
            print(f"Error extracting base from variant {variant_id}: {e}")
            continue
    
    if not expected_root_nouns:
        print("No valid expected root nouns found")
        return 0, "Error: Unable to extract valid expected answers."
    
    # Compare student's root noun with expected root nouns
    if student_root_noun in expected_root_nouns:
        print(f"Match found! Student root noun '{student_root_noun}' matches expected root noun(s)")
        return 2, f"You chose as base \"{student_base}\". This is correct."
    else:
        # Format expected bases for feedback
        expected_bases_str = ", ".join(expected_bases) if expected_bases else "unknown"
        feedback = f"Your base is different from the expected base. Expected base(s): {expected_bases_str}"
        print(f"No match. Student: '{student_root_noun}', Expected: {expected_root_nouns}")
        return 0, feedback

import json

def _normalize_cell_reference(cell_ref):
    """Remove $ signs from cell reference for flexible matching."""
    if not cell_ref:
        return ""
    return cell_ref.replace("$", "").lower()

def _series_matches(student_series, expected_series):
    """
    Check if a student series matches an expected series.
    Flexible matching: ignore $ signs, case-insensitive.
    """
    student_values = student_series.get("values", {})
    student_xvalues = student_series.get("xvalues", {})
    
    expected_values_ref = expected_series.get("expected_values_reference", "")
    expected_xvalues_ref = expected_series.get("expected_xvalues_reference", "")
    
    # Normalize and compare values
    student_values_norm = _normalize_cell_reference(
        student_values.get("value", "")
    )
    expected_values_norm = _normalize_cell_reference(expected_values_ref)
    
    # Normalize and compare xvalues
    student_xvalues_norm = _normalize_cell_reference(
        student_xvalues.get("value", "")
    )
    expected_xvalues_norm = _normalize_cell_reference(expected_xvalues_ref)
    
    # Both values and xvalues must match
    values_match = student_values_norm == expected_values_norm
    xvalues_match = student_xvalues_norm == expected_xvalues_norm
    
    return values_match and xvalues_match

def mark_chart_answer(chartdata_json, cursor, question_md_id):
    """Mark a chart answer based on question_chart_rule and question_chart_arguments.
    
    Logic:
    1. Parse JSON, extract first chart
    2. Fetch chart rule for the question
    3. Validate required properties: chart_type, title, legend, x/y-axis titles
    4. Validate at least one student series matches a rule series
    5. Calculate mark from marks_config
    
    Returns:
        tuple: (mark, feedback) where mark is int and feedback is str
    """
    print(f"Marking chart answer for question_md_id: {question_md_id}")
    
    if not chartdata_json:
        print("No chart data provided")
        return 0, "No chart data provided."
    
    # Parse JSON
    try:
        chart_data = json.loads(chartdata_json) if isinstance(chartdata_json, str) else chartdata_json
        charts = chart_data.get("charts", [])
        
        if not charts:
            print("No charts found in chartdata")
            return 0, "No charts found in submission."
        
        student_chart = charts[0]  # First chart
        chart_title = student_chart.get("title", "Untitled")
        chart_label = f"Chart '{chart_title}'" if chart_title else "Chart 1"
        
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Error parsing chartdata JSON: {e}")
        return 0, f"Error parsing chart data: {str(e)}"
    
    # Fetch active chart rule
    cursor.execute(
        """
        SELECT question_chart_rule_id, chart_type, marks_config, 
               require_title, require_legend, require_x_axis_title, require_y_axis_title
        FROM question_chart_rule
        WHERE question_md_id = %s AND is_active = TRUE
        ORDER BY question_chart_rule_id ASC
        LIMIT 1
        """,
        [question_md_id]
    )
    rule_row = cursor.fetchone()
    
    if not rule_row:
        print(f"No active chart rule found for question_md_id: {question_md_id}")
        return 0, "No chart rule found for this question."
    
    (rule_id, expected_chart_type, marks_config_json, 
     require_title, require_legend, require_x_axis_title, require_y_axis_title) = rule_row
    
    print(f"Using chart rule_id: {rule_id}, expected type: {expected_chart_type}")
    
    # Parse marks_config
    try:
        marks_config = marks_config_json if isinstance(marks_config_json, list) else json.loads(marks_config_json)
    except (json.JSONDecodeError, TypeError):
        marks_config = []
    
    # Initialize mark and feedback
    mark = 0
    feedback_parts = []
    total_marks_available = sum(item.get("marks", 0) for item in marks_config)
    
    # Validate chart_type
    student_chart_type = str(student_chart.get("chart type", ""))
    if student_chart_type == str(expected_chart_type):
        mark += next((item["marks"] for item in marks_config if item["property"] == "chart_type"), 0)
        feedback_parts.append(f"✓ Chart type '{student_chart_type}' matches expected type.")
        print(f"Chart type match: {student_chart_type}")
    else:
        feedback_parts.append(f"✗ Chart type '{student_chart_type}' does not match expected type '{expected_chart_type}'.")
        print(f"Chart type mismatch: {student_chart_type} vs {expected_chart_type}")
    
    # Validate title (presence only)
    student_title = student_chart.get("title", "").strip()
    if require_title:
        if student_title:
            mark += next((item["marks"] for item in marks_config if item["property"] == "title"), 0)
            feedback_parts.append(f"✓ Title present: '{student_title}'.")
            print("Title present")
        else:
            feedback_parts.append("✗ Title is required but missing.")
            print("Title missing")
    
    # Validate legend (presence only)
    has_legend = "legend position" in student_chart
    if require_legend:
        if has_legend:
            mark += next((item["marks"] for item in marks_config if item["property"] == "legend"), 0)
            feedback_parts.append("✓ Legend is present.")
            print("Legend present")
        else:
            feedback_parts.append("✗ Legend is required but missing.")
            print("Legend missing")
    
    # Validate x-axis title (presence only)
    x_axis_title = student_chart.get("x-axis title", "").strip()
    if require_x_axis_title:
        if x_axis_title:
            mark += next((item["marks"] for item in marks_config if item["property"] == "x_axis_title"), 0)
            feedback_parts.append(f"✓ X-axis title present: '{x_axis_title}'.")
            print("X-axis title present")
        else:
            feedback_parts.append("✗ X-axis title is required but missing.")
            print("X-axis title missing")
    
    # Validate y-axis title (presence only)
    y_axis_title = student_chart.get("y-axis title", "").strip()
    if require_y_axis_title:
        if y_axis_title:
            mark += next((item["marks"] for item in marks_config if item["property"] == "y_axis_title"), 0)
            feedback_parts.append(f"✓ Y-axis title present: '{y_axis_title}'.")
            print("Y-axis title present")
        else:
            feedback_parts.append("✗ Y-axis title is required but missing.")
            print("Y-axis title missing")
    
    # Validate series data
    cursor.execute(
        """
        SELECT argument_id, expected_values_reference, expected_xvalues_reference, is_required
        FROM question_chart_arguments
        WHERE question_chart_rule_id = %s
        ORDER BY series_index ASC
        """,
        [rule_id]
    )
    expected_series_list = cursor.fetchall()
    
    student_series_list = student_chart.get("series data", [])
    
    if expected_series_list:
        # Check if at least one student series matches a rule series
        series_match_found = False
        
        for expected_series_row in expected_series_list:
            argument_id, exp_values_ref, exp_xvalues_ref, is_required = expected_series_row
            
            expected_series = {
                "expected_values_reference": exp_values_ref,
                "expected_xvalues_reference": exp_xvalues_ref,
                "is_required": is_required
            }
            
            # Check if any student series matches this expected series
            for student_series in student_series_list:
                if _series_matches(student_series, expected_series):
                    series_match_found = True
                    break
            
            if series_match_found:
                break
        
        if series_match_found:
            mark += next((item["marks"] for item in marks_config if item["property"] == "series_data"), 0)
            feedback_parts.append("✓ Series data matches expected data.")
            print("Series data match")
        else:
            feedback_parts.append("✗ Series data does not match expected data.")
            print("Series data mismatch")
    
    feedback = " ".join(feedback_parts)
    print(f"Final mark: {mark}/{total_marks_available}")
    
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
            cursor.execute("SELECT COUNT(*) FROM answers WHERE sessionid = %s", [sessionid])
            count = cursor.fetchone()[0]
            print(f"Step 2b: COUNT(*) for sessionid {sessionid} = {count}")

            cursor.execute(
            "SELECT sessionid, questionid, answertext, answervalue, answerformula, chartdata FROM answers WHERE sessionid = %s",
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
    
    for orig_sessionid, questionid, answertext, answervalue, answerformula, chartdata in answers:
        feedback = None
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT question_md_id, question_type, question_sol FROM question_md WHERE question_id = %s",
                [questionid]
            )
            row = cursor.fetchone()

            if not row:
                mark = 0
                feedback = "No solution found."
            else:
                question_md_id, question_type, solution = row
                print(f"DEBUG: question_id={questionid}, question_type='{question_type}', question_md_id={question_md_id}")  # ADD THIS
                print(f"Comparing answer '{answertext}' to solution '{solution}'")

            if not row:
                mark = 0  # or handle missing solution
                feedback = "No solution found."
            else:
                question_md_id, question_type, solution = row
                print(f"Comparing answer '{answertext}' to solution '{solution}'")
                # Mark based on question type
                if question_type == 'boolean':
                    print(f"Marking boolean question for questionid {questionid}")
                    mark = mark_boolean_answer(answertext, solution)
                    feedback = "Correct." if mark else "Incorrect."
                elif question_type == 'value':
                    print(f"Marking value question for questionid {questionid}, with answervalue {answervalue} and solution {solution}")
                    mark = mark_value_answer(answervalue, solution, cursor, question_md_id)
                    feedback = "Correct." if mark else "Incorrect."
                elif question_type == 'formula':
                    print(f"Marking formula question for questionid {questionid}, with formula {answerformula}")
                    mark, feedback = mark_formula_answer(answerformula, cursor, question_md_id)
                elif question_type == 'nlp':
                    print(f"Marking NLP question for questionid {questionid}, with answer text {answertext}")
                    mark, feedback = mark_nlp_answer(answertext, cursor, question_md_id)
                elif question_type == 'chart':
                    print(f"Marking chart question for questionid {questionid}")
                    mark, feedback = mark_chart_answer(chartdata, cursor, question_md_id)
                else:
                    print(f"Unknown question type '{question_type}' for questionid {questionid}")
                    mark = 0
                    feedback = "Unknown question type."

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE answers SET markawarded = %s, feedback = %s WHERE sessionid = %s AND questionid = %s",
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