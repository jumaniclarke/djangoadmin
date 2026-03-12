from django.utils import timezone

from django.db import connection
from .pandas_automation import get_base, extract_number_from_noun_phrase

    
def mark_mcq_answer(answertext, cursor, question_md_id):
    """
    Mark an MCQ answer using rules from question_mcq_rule.
    Returns (mark, feedback).
    """
    # Fetch MCQ rule for the question
    cursor.execute(
        """
        SELECT mcq_mode, valid_labels, correct_options, scoring_policy, full_marks, negative_marks, allow_blank, blank_marks, case_sensitive
        FROM question_mcq_rule WHERE question_md_id = %s LIMIT 1
        """,
        [question_md_id]
    )
    rule = cursor.fetchone()
    if not rule:
        return 0, 1, "No MCQ rule found."
    (
        mcq_mode, valid_labels, correct_options, scoring_policy, full_marks, negative_marks, allow_blank, blank_marks, case_sensitive
    ) = rule

    # Parse valid_labels and correct_options (assume text fields with e.g. '{"pie chart", "bar chart"}')
    import json
    def parse_set(text):
        if isinstance(text, (list, set)):
            return set(text)
        try:
            if text.strip().startswith('{'):
                return set(json.loads(text.replace("'", '"').replace('{', '[').replace('}', ']')))
            return set(json.loads(text))
        except Exception:
            return set()
    valid_labels = parse_set(valid_labels)
    correct_options = parse_set(correct_options)

    # Case sensitivity
    def norm(s):
        return s if case_sensitive else s.lower()
    valid_labels = set(map(norm, valid_labels))
    correct_options = set(map(norm, correct_options))

    # Normalize answer
    answer = answertext.strip() if answertext else ''
    norm_answer = norm(answer)


    # Allow blank
    if allow_blank and not answer:
        return blank_marks if blank_marks is not None else 0, 1, "Blank allowed."
    if not answer:
        return negative_marks if negative_marks is not None else 0, 1, "No answer provided."
    if norm_answer not in valid_labels:
        return negative_marks if negative_marks is not None else 0, 1, f"Invalid option: {answer}."

    # Marking logic
    max_raw = full_marks if full_marks is not None else 1
    if mcq_mode == 'single':
        if norm_answer in correct_options:
            return max_raw, max_raw, "Correct."
        else:
            return 0, max_raw, "Incorrect."
    elif mcq_mode == 'multiple':
        selected = set(map(lambda x: norm(x.strip()), answer.split(',')))
        if not selected:
            return blank_marks if blank_marks is not None else 0, max_raw, "Blank allowed."
        if not selected.issubset(valid_labels):
            return negative_marks if negative_marks is not None else 0, max_raw, "Invalid option(s) selected."
        n_correct = len(correct_options)
        n_selected_correct = len(selected & correct_options)
        if n_correct == 0:
            return 0, max_raw, "No correct options configured."
        partial_mark = (max_raw * n_selected_correct) / n_correct
        if scoring_policy == 'all_or_nothing':
            if selected == correct_options:
                return max_raw, max_raw, "All correct options selected."
            else:
                return 0, max_raw, "Not all correct options selected."
        else:
            return partial_mark, max_raw, f"{n_selected_correct}/{n_correct} correct options selected."
    else:
        return 0, max_raw, f"Unknown MCQ mode: {mcq_mode}."
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import re
from .pandas_automation import get_base, extract_number_from_noun_phrase
#from .chart_lookup.xl_chart_types import CODE_TO_META

def mark_boolean_answer(answertext, solution):
    """Mark a boolean answer (case-insensitive exact match)."""
    # Boolean questions are always 0 or 1
    mark = 1 if str(answertext).strip().lower() == str(solution).strip().lower() else 0
    return mark, 1, ("Correct." if mark else "Incorrect.")

def mark_value_answer(answervalue, solution, cursor, question_md_id):
    """Mark a value answer with tolerance range from question_value_rule."""
    import math
    try:
        answer_str = str(answervalue).replace(',', '').strip()
        solution_str = str(solution).replace(',', '').strip()
        try:
            answer_float = float(answer_str)
        except (ValueError, TypeError):
            extracted = extract_number_from_noun_phrase(answer_str)
            if extracted is not None:
                answer_float = float(extracted.replace(',', '').strip())
            else:
                return 0, 1, "Could not extract a number."
        solution_float = float(solution_str)
        cursor.execute(
            "SELECT tol_value FROM question_value_rule WHERE question_md_id = %s",
            [question_md_id]
        )
        tol_row = cursor.fetchone()
        max_raw = 1
        if not tol_row:
            mark = 1 if math.isclose(answer_float, solution_float, rel_tol=1e-9) else 0
            return mark, max_raw, "Correct." if mark else "Incorrect."
        tol_percent = float(tol_row[0]) / 100.0
        tolerance = abs(solution_float) * tol_percent
        lower_bound = solution_float - tolerance
        upper_bound = solution_float + tolerance
        in_range = lower_bound <= answer_float <= upper_bound
        mark = 1 if in_range else 0
        return mark, max_raw, "Correct." if mark else "Incorrect."
    except (ValueError, TypeError) as e:
        return 0, 1, "Invalid input."

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
    feedback_parts = []
    
    if not answerformula:
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
        return 0, "No formula rule found for this question."

    rule_id, function_name, arg_count, match_policy, case_insensitive, ignore_whitespace = rule_row

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

    feedback = "".join(feedback_parts)
    max_raw = 1 + len(expected_args) if expected_args else 1
    return mark, max_raw, feedback

_sentence_transformer_model = None
_variant_embedding_cache = {}  # {question_nlp_rule_id: np.ndarray shape (n_variants, dim)}

def _get_sentence_model():
    """Lazy-load and cache the sentence-transformers model."""
    global _sentence_transformer_model
    if _sentence_transformer_model is None:
        from sentence_transformers import SentenceTransformer
        _sentence_transformer_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _sentence_transformer_model

def mark_nlp_answer(answertext, cursor, question_md_id, student_embedding=None):
    """Mark an NLP answer using semantic similarity via sentence-transformers.

    Compares the student's answer against all active phrase variants using
    cosine similarity. Returns full marks if the best similarity score meets
    the overall_similarity_threshold configured in question_nlp_rule.
    The 'proportion' type retains its existing base-form matching logic.

    Returns:
        tuple: (raw_mark, raw_max, feedback)
    """
    if not answertext:
        return 0, 2, "No answer provided."

    # Fetch the active NLP rule for this question
    cursor.execute(
        """
        SELECT question_nlp_rule_id, language, spacy_model, type, overall_similarity_threshold
        FROM question_nlp_rule
        WHERE question_md_id = %s AND is_active = TRUE
        ORDER BY question_nlp_rule_id ASC
        LIMIT 1
        """,
        [question_md_id]
    )
    rule_row = cursor.fetchone()
    if not rule_row:
        return 0, 2, "No NLP rule found for this question."
    question_nlp_rule_id, language, spacy_model, nlp_type, overall_similarity_threshold = rule_row

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
        return 0, 2, "No phrase variants found for this question."

    if nlp_type in ('noun-phrase', 'verb-phrase'):
        from sentence_transformers import util as st_util
        threshold = float(overall_similarity_threshold) if overall_similarity_threshold is not None else 0.75
        model = _get_sentence_model()

        # Use pre-computed student embedding if provided (batch path), else encode now
        if student_embedding is None:
            student_embedding = model.encode(answertext.strip())

        # Batch-encode all variants once per rule and cache permanently
        if question_nlp_rule_id not in _variant_embedding_cache:
            valid_phrases = [pt.strip() for _, pt in phrase_variants if pt and pt.strip()]
            if not valid_phrases:
                return 0, 2, "No phrase variants found for this question."
            _variant_embedding_cache[question_nlp_rule_id] = model.encode(valid_phrases)
        variant_embeddings = _variant_embedding_cache[question_nlp_rule_id]

        # Compute all similarities in one vectorised call
        scores = st_util.cos_sim(student_embedding, variant_embeddings)[0]
        best_score = float(scores.max().item())

        if best_score >= threshold:
            return 2, 2, "Your answer is correct."
        else:
            return 0, 2, "Your answer does not match the expected answer."
    else:
        # 'proportion' and other types: extract base form, then compare semantically
        from sentence_transformers import util as st_util
        threshold = float(overall_similarity_threshold) if overall_similarity_threshold is not None else 0.75
        model = _get_sentence_model()

        student_base = get_base(answertext.strip())
        print(f"Answer text: {answertext.strip()}")
        print(f"Extracted base form from student's answer: '{student_base}'")
        if not student_base or not student_base.strip():
            return 0, 2, "Could not extract a base form from your answer."

        student_base_embedding = model.encode(student_base.strip())

        # Cache variant base-form embeddings separately (keyed with '_base' suffix)
        cache_key = f"{question_nlp_rule_id}_base"
        if cache_key not in _variant_embedding_cache:
            valid_bases = [get_base(pt.strip()) for _, pt in phrase_variants if pt and pt.strip()]
            valid_bases = [b for b in valid_bases if b and b.strip()]
            if not valid_bases:
                return 0, 2, "No phrase variants found for this question."
            _variant_embedding_cache[cache_key] = (valid_bases, model.encode(valid_bases))
        expected_bases, variant_base_embeddings = _variant_embedding_cache[cache_key]

        scores = st_util.cos_sim(student_base_embedding, variant_base_embeddings)[0]
        best_score = float(scores.max().item())

        if best_score >= threshold:
            return 2, 2, f"You chose as whole \"{student_base}\". This is correct."
        else:
            expected_bases_str = ", ".join(expected_bases) if expected_bases else "unknown"
            return 0, 2, f"Your whole is \"{student_base}\", which is different from the expected whole: {expected_bases_str}"

import json
import os
import math

# Load chart type lookup
CHART_LOOKUP_PATH = os.path.join(os.path.dirname(__file__), 'chart_lookup', 'xl_chart_types.json')
with open(CHART_LOOKUP_PATH, 'r') as f:
    CHART_LOOKUP = json.load(f)

def _format_mark(mark_value):
    """Format a mark value as int if whole number, else as float with 1 decimal."""
    try:
        m = float(mark_value)
        if math.isclose(m, round(m), abs_tol=1e-9):
            return int(round(m))
        else:
            return round(m, 1)
    except (ValueError, TypeError):
        return mark_value

def _normalize_cell_reference(cell_ref):
    """Remove $ signs from cell reference for flexible matching."""
    if not cell_ref:
        return ""
    return cell_ref.replace("$", "").lower()

def _format_chart_name(chart_name):
    """
    Format chart type name for readable feedback.
    Removes 'xl' prefix and adds spaces before capital letters.
    
    Examples:
        'xlPie' -> 'Pie'
        'xlColumn' -> 'Column'
        'xlCylinderColClustered' -> 'Cylinder Col Clustered'
    """
    if not chart_name:
        return chart_name
    
    # Remove 'xl' prefix if present
    name = chart_name
    if name.startswith('xl'):
        name = name[2:]
    
    # Add space before each capital letter (except the first one)
    formatted = ''
    for i, char in enumerate(name):
        if i > 0 and char.isupper():
            formatted += ' '
        formatted += char
    
    return formatted

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
    if not chartdata_json:
        return 0, "No chart data provided."
    # Parse JSON
    try:
        chart_data = json.loads(chartdata_json) if isinstance(chartdata_json, str) else chartdata_json
        charts = chart_data.get("charts", [])
        if not charts:
            return 0, "No charts found in submission."
        student_chart = charts[0]  # First chart
        chart_title = student_chart.get("title", "Untitled")
        chart_label = f"Chart '{chart_title}'" if chart_title else "Chart 1"
    except (json.JSONDecodeError, TypeError) as e:
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
        return 0, "No chart rule found for this question."
    
    (rule_id, expected_chart_type, marks_config_json, 
     require_title, require_legend, require_x_axis_title, require_y_axis_title) = rule_row
    
    # ...existing code...
    
    # Parse marks_config
    try:
        marks_config = marks_config_json if isinstance(marks_config_json, list) else json.loads(marks_config_json)
    except (json.JSONDecodeError, TypeError):
        marks_config = []
    
    # Initialize mark and feedback
    mark = 0
    feedback_parts = []
    total_marks_available = sum(item.get("marks", 0) for item in marks_config)
    max_raw = total_marks_available if total_marks_available > 0 else 1
    
    # Validate chart_type
    student_chart_type_code = str(student_chart.get("chart type", ""))
    
    # Look up category from code
    code_to_meta = CHART_LOOKUP.get("code_to_meta", {})
    student_chart_meta = code_to_meta.get(student_chart_type_code)
    
    chart_type_marks = next((item["marks"] for item in marks_config if item["property"] == "chart_type"), 0)
    
    if not student_chart_meta:
        feedback_parts.append(f"<span style='color: red; font-weight: bold;'>✗</span> Chart type code '{student_chart_type_code}' not recognized. [0/{_format_mark(chart_type_marks)} mark(s)]")
    else:
        student_chart_type = student_chart_meta.get("category", "")
        student_chart_name = student_chart_meta.get("name", "")
        formatted_chart_name = _format_chart_name(student_chart_name)
        formatted_expected_chart_name = _format_chart_name(expected_chart_type)
        if str(student_chart_name).strip().lower() == str(expected_chart_type).strip().lower():
            mark += chart_type_marks
            feedback_parts.append(f"<span style='color: red; font-weight: bold;'>✓</span> Your chart type is correct [{_format_mark(chart_type_marks)}/{_format_mark(chart_type_marks)} mark(s)]")
        else:
            feedback_parts.append(f"<span style='color: red; font-weight: bold;'>✗</span> Your chart type is '{formatted_chart_name}' but expected type is '{formatted_expected_chart_name}'. [0/{_format_mark(chart_type_marks)} mark(s)]")
    
    # Validate title (presence only)
    student_title = student_chart.get("title", "").strip()
    if require_title:
        title_marks = next((item["marks"] for item in marks_config if item["property"] == "title"), 0)
        if student_title:
            mark += title_marks
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✓</span> Title present: '{student_title}'. [{_format_mark(title_marks)}/{_format_mark(title_marks)} mark(s)]")
            #print("Title present")
        else:
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✗</span> Title is required but missing. [0/{_format_mark(title_marks)} mark(s)]")
            #print("Title missing")
    
    # Validate legend (presence only)
    has_legend = "legend position" in student_chart
    if require_legend:
        legend_marks = next((item["marks"] for item in marks_config if item["property"] == "legend"), 0)
        if has_legend:
            mark += legend_marks
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✓</span> Legend is present. [{_format_mark(legend_marks)}/{_format_mark(legend_marks)} mark(s)]")
            # ...existing code...
        else:
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✗</span> Legend is required but missing. [0/{_format_mark(legend_marks)} mark(s)]")
            #print("Legend missing")
    
    # Validate x-axis title (presence only)
    x_axis_title = student_chart.get("x-axis title", "").strip()
    if require_x_axis_title:
        x_axis_marks = next((item["marks"] for item in marks_config if item["property"] == "x_axis_title"), 0)
        if x_axis_title:
            mark += x_axis_marks
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✓</span> X-axis title present: '{x_axis_title}'. [{_format_mark(x_axis_marks)}/{_format_mark(x_axis_marks)} mark(s)]")
            #print("X-axis title present")
        else:
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✗</span> X-axis title is required but missing. [0/{_format_mark(x_axis_marks)} mark(s)]")
            #print("X-axis title missing")
    
    # Validate y-axis title (presence only)
    y_axis_title = student_chart.get("y-axis title", "").strip()
    if require_y_axis_title:
        y_axis_marks = next((item["marks"] for item in marks_config if item["property"] == "y_axis_title"), 0)
        if y_axis_title:
            mark += y_axis_marks
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✓</span> Y-axis title present: '{y_axis_title}'. [{_format_mark(y_axis_marks)}/{_format_mark(y_axis_marks)} mark(s)]")
            #print("Y-axis title present")
        else:
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✗</span> Y-axis title is required but missing. [0/{_format_mark(y_axis_marks)} mark(s)]")
            #print("Y-axis title missing")
    
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
        # Check matches for full/partial credit
        series_marks = next((item["marks"] for item in marks_config if item["property"] == "series_data"), 0)
        full_match_found = False
        partial_match_found = False
        values_match_found = False
        xvalues_match_found = False
        full_match_pair = None
        values_match_pair = None
        xvalues_match_pair = None

        for expected_series_row in expected_series_list:
            _, exp_values_ref, exp_xvalues_ref, is_required = expected_series_row

            expected_series = {
                "expected_values_reference": exp_values_ref,
                "expected_xvalues_reference": exp_xvalues_ref,
                "is_required": is_required
            }

            expected_values_norm = _normalize_cell_reference(exp_values_ref)
            expected_xvalues_norm = _normalize_cell_reference(exp_xvalues_ref)

            for student_series in student_series_list:
                student_values_raw = student_series.get("values", {}).get("value", "")
                student_xvalues_raw = student_series.get("xvalues", {}).get("value", "")
                student_values_norm = _normalize_cell_reference(student_values_raw)
                student_xvalues_norm = _normalize_cell_reference(student_xvalues_raw)

                values_match = student_values_norm == expected_values_norm
                xvalues_match = student_xvalues_norm == expected_xvalues_norm

                if values_match:
                    values_match_found = True
                    if values_match_pair is None:
                        values_match_pair = (student_values_raw, exp_values_ref, student_xvalues_raw, exp_xvalues_ref)
                if xvalues_match:
                    xvalues_match_found = True
                    if xvalues_match_pair is None:
                        xvalues_match_pair = (student_values_raw, exp_values_ref, student_xvalues_raw, exp_xvalues_ref)

                if values_match and xvalues_match:
                    full_match_found = True
                    if full_match_pair is None:
                        full_match_pair = (student_values_raw, exp_values_ref, student_xvalues_raw, exp_xvalues_ref)
                    break
                if values_match or xvalues_match:
                    partial_match_found = True

            if full_match_found:
                break

        if full_match_found:
            mark += series_marks
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✓</span> Your series data matches the expected data. [{_format_mark(series_marks)}/{_format_mark(series_marks)} mark(s)]")
            if full_match_pair:
                s_vals, e_vals, s_xvals, e_xvals = full_match_pair
                feedback_parts.append(f"\n\t<span style='color: red; font-weight: bold;'>✓</span> Values match:\n\t\tyours = {s_vals}\n\t\texpected = {e_vals}")
                feedback_parts.append(f"\n\t<span style='color: red; font-weight: bold;'>✓</span> X-values match:\n\t\tyours = {s_xvals}\n\t\texpected = {e_xvals}")
            #print("Series data full match")
        elif partial_match_found:
            half_marks = round(series_marks / 2, 1)
            mark += half_marks
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>△</span> Your series data partially matches the expected data. [{_format_mark(half_marks)}/{_format_mark(series_marks)} mark(s)]")
            # Values match but x-values do not
            if values_match_found and not xvalues_match_found:
                feedback_parts.append("\n\t<span style='color: red; font-weight: bold;'>✓</span> Values match, but x-values do not.")
                if values_match_pair:
                    s_vals, e_vals, s_xvals, e_xvals = values_match_pair
                    feedback_parts.append(f"\n\t\t<span style='color: red; font-weight: bold;'>✓</span> Values match:\n\t\t\t\tyours = {s_vals}\n\t\t\t\texpected = {e_vals}")
                    feedback_parts.append(f"\n\t\t<span style='color: red; font-weight: bold;'>✗</span> X-values do not match:\n\t\t\t\tyours = {s_xvals}\n\t\t\t\texpected = {e_xvals}")
            # X-values match but values do not
            elif xvalues_match_found and not values_match_found:
                feedback_parts.append("\n\t\t<span style='color: red; font-weight: bold;'>✓</span> X-values match, but values do not.")
                if xvalues_match_pair:
                    s_vals, e_vals, s_xvals, e_xvals = xvalues_match_pair
                    feedback_parts.append(f"\n\t\t<span style='color: red; font-weight: bold;'>✓</span> X-values match:\n\t\t\t\tyours = {s_xvals}\n\t\t\t\texpected = {e_xvals}")
                    feedback_parts.append(f"\n\t\t<span style='color: red; font-weight: bold;'>✗</span> Values do not match:\n\t\t\t\tyours = {s_vals}\n\t\t\t\texpected = {e_vals}")
            # Both matched somewhere but not in the same series
            elif values_match_found and xvalues_match_found:
                feedback_parts.append("\n\t\t<span style='color: red; font-weight: bold;'>✓</span> Values and x-values each matched at least once, but not in the same series.")
                if values_match_pair:
                    s_vals, e_vals, s_xvals, e_xvals = values_match_pair
                    feedback_parts.append(f"\n\t\t<span style='color: red; font-weight: bold;'>✓</span> Values match:\n\t\t\t\tyours = {s_vals}\n\t\t\t\texpected = {e_vals}")
                    feedback_parts.append(f"\n\t\t<span style='color: red; font-weight: bold;'>✗</span> X-values do not match:\n\t\t\t\tyours = {s_xvals}\n\t\t\t\texpected = {e_xvals}")
                if xvalues_match_pair:
                    s_vals, e_vals, s_xvals, e_xvals = xvalues_match_pair
                    feedback_parts.append(f"\n\t\t<span style='color: red; font-weight: bold;'>✓</span> X-values match:\n\t\t\t\tyours = {s_xvals}\n\t\t\t\texpected = {e_xvals}")
                    feedback_parts.append(f"\n\t\t<span style='color: red; font-weight: bold;'>✗</span> Values do not match:\n\t\t\t\tyours = {s_vals}\n\t\t\t\texpected = {e_vals}")
            #print("Series data partial match")
        else:
            # Provide detailed feedback on mismatch
            feedback_parts.append(f"\n<span style='color: red; font-weight: bold;'>✗</span> Your series data does not match the expected data. [0/{_format_mark(series_marks)} mark(s)]")
            
            # Show what student provided
            if student_series_list:
                student_series_count = len(student_series_list)
                for idx, student_series in enumerate(student_series_list):
                    student_values = student_series.get("values", {}).get("value", "N/A")
                    student_xvalues = student_series.get("xvalues", {}).get("value", "N/A")
                    if student_series_count == 1:
                        label = "Your chart data"
                    else:
                        label = f"Your chart data series {idx+1}"
                    feedback_parts.append(f"\n  {label}: values={student_values}, xvalues={student_xvalues}")
            else:
                feedback_parts.append("\n  You provided no series data.")
            
            # Show what was expected
            expected_series_count = len(expected_series_list)
            feedback_parts.append("\n  Expected:")
            for idx, expected_series_row in enumerate(expected_series_list):
                _, exp_values_ref, exp_xvalues_ref, _ = expected_series_row
                if expected_series_count == 1:
                    label = "Chart data"
                else:
                    label = f"Chart data series {idx+1}"
                feedback_parts.append(f"\n    {label}: values = {exp_values_ref or 'N/A'}, xvalues = {exp_xvalues_ref or 'N/A'}")
            
            #print("Series data mismatch")
    
    try:
        m = float(mark)
    except Exception:
        pass
    else:
        if math.isclose(m, round(m), abs_tol=1e-9):
            mark = int(round(m))
        else:
            mark = round(m, 1)

    feedback = "".join(feedback_parts)
    return mark, max_raw, feedback

def mark_answers_for_session(sessionid, force=False):
    """
    For a given sessionid, fetch all answers, compare to solutions in question_md,
    and update the markawarded column in answers.

    Batches WebSocket broadcasts to reduce network overhead.

    Args:
        force: If True, bypass deadline checks (used for admin-triggered marking).
    """
    # Force fresh connection state to avoid stale data
    connection.close()

    # Collect all marks before broadcasting
    marked_answers = []

    # --- DEADLINE LOGIC ---
    with connection.cursor() as cursor:
        # Get session info: studentnumber, workbookname
        cursor.execute("SELECT studentnumber, workbookname FROM sessions WHERE sessionid = %s", [sessionid])
        session_row = cursor.fetchone()
        if not session_row:
            return
        studentnumber, workbookname = session_row
        # Parse workbookname: first 8 = course code, next 4 = tutorial name
        course_code = workbookname[:8]
        tutorial_name = workbookname[8:12]

        if not force:
            # Get student class, courseid, oyear
            cursor.execute("SELECT class, courseid, oyear FROM studentclassesnew WHERE studentid = %s AND courseid = %s", [studentnumber, course_code])
            sc_row = cursor.fetchone()
            if not sc_row:
                return
            class_code, courseid, oyear = sc_row
            # Find deadlines
            cursor.execute("""
                SELECT deadline_id, workbookname, courseid, oyear, scope_level, class_code, studentid, start_at, end_at
                FROM student_deadlines
                WHERE LOWER(workbookname) = LOWER(%s) AND LOWER(courseid) = LOWER(%s) AND oyear = %s
            """, [tutorial_name, courseid, oyear])
            deadlines = cursor.fetchall()
            # Find best matching deadline
            deadline = None
            # 1. Prefer student-level
            for d in deadlines:
                if d[4] == 'student' and d[6] == studentnumber:
                    deadline = d
                    break
            # 2. Else class-level
            if not deadline:
                for d in deadlines:
                    if d[4] == 'class' and d[5] == class_code:
                        deadline = d
                        break
            # 3. Else course-level
            if not deadline:
                for d in deadlines:
                    if d[4] == 'course':
                        deadline = d
                        break
            if not deadline:
                return
            # Check deadline window
            start_at, end_at = deadline[7], deadline[8]
            if not (start_at and end_at):
                return
            if not (start_at <= timezone.now() <= end_at):
                return

        # Now fetch answers as before
        try:
            cursor.execute("SELECT sessionid, questionid, answertext, answervalue, answerformula, chartdata FROM answers WHERE sessionid = %s", [sessionid])
            answers = list(cursor.fetchall())
        except Exception as e:
            return
    if not answers:
        #print("answers is empty or exhausted")
        return

    # Pre-batch encode all NLP student answers in a single model call
    nlp_embeddings = {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.questionid, a.answertext
            FROM answers a
            JOIN question_md qm ON qm.question_id = a.questionid
            WHERE a.sessionid = %s AND qm.question_type = 'nlp'
              AND a.answertext IS NOT NULL AND a.answertext <> ''
            """,
            [sessionid]
        )
        nlp_text_rows = cursor.fetchall()
    if nlp_text_rows:
        valid = [(qid, txt.strip()) for qid, txt in nlp_text_rows if txt and txt.strip()]
        if valid:
            qids, texts = zip(*valid)
            embeddings = _get_sentence_model().encode(list(texts))
            nlp_embeddings = dict(zip(qids, embeddings))

    for orig_sessionid, questionid, answertext, answervalue, answerformula, chartdata in answers:
        feedback = None
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT question_md_id, question_type, question_sol, marks FROM question_md WHERE question_id = %s",
                [questionid]
            )
            row = cursor.fetchone()
            if not row:
                mark = 0
                max_raw = 1
                feedback = "No solution found."
                rescaled_mark = 0
            else:
                question_md_id, question_type, solution, max_mark = row
                if max_mark is None:
                    max_mark = 1
                # Mark based on question type
                if question_type == 'boolean':
                    raw_mark, raw_max, fb = mark_boolean_answer(answertext, solution)
                elif question_type == 'value':
                    raw_mark, raw_max, fb = mark_value_answer(answertext, solution, cursor, question_md_id)
                elif question_type == 'formula':
                    raw_mark, raw_max, fb = mark_formula_answer(answerformula, cursor, question_md_id)
                elif question_type == 'nlp':
                    raw_mark, raw_max, fb = mark_nlp_answer(answertext, cursor, question_md_id,
                                                            student_embedding=nlp_embeddings.get(questionid))
                elif question_type == 'chart':
                    raw_mark, raw_max, fb = mark_chart_answer(chartdata, cursor, question_md_id)
                elif question_type == 'mcq':
                    raw_mark, raw_max, fb = mark_mcq_answer(answertext, cursor, question_md_id)
                else:
                    raw_mark, raw_max, fb = 0, 1, "Unknown question type."
                # Rescale
                try:
                    rescaled_mark = round((float(raw_mark) / float(raw_max)) * float(max_mark), 2) if raw_max else 0
                except Exception:
                    rescaled_mark = 0
                feedback = f"{fb}\n[Raw: {raw_mark}/{raw_max}, Rescaled: {rescaled_mark}/{max_mark}]"

        with connection.cursor() as cursor:
            feedback_clean = feedback.replace("<span style='color: red; font-weight: bold;'>", "").replace("</span>", "") if feedback else feedback
            cursor.execute(
                "UPDATE answers SET markawarded = %s, feedback = %s WHERE sessionid = %s AND questionid = %s",
                [rescaled_mark, feedback_clean, orig_sessionid, questionid]
            )
        marked_answers.append({
            "sessionid": orig_sessionid,
            "questionid": questionid,
            "mark": rescaled_mark,
            "feedback": feedback
        })
    
    # Broadcast all marks for this session at once (batch operation)
    if marked_answers:
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"session_{orig_sessionid}",
                {
                    "type": "batch_mark_update",
                    "marks": marked_answers
                }
            )
            #print(f"✓ Batch broadcast {len(marked_answers)} marks for session {orig_sessionid}")
        except Exception as e:
            print(f"Batch broadcast failed for session {orig_sessionid}: {e}")

    # --- Update studentgradesnew with total marks ---
    # Sum all rescaled marks (markawarded) for this session
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT SUM(markawarded) FROM answers WHERE sessionid = %s",
            [sessionid]
        )
        total_marks = cursor.fetchone()[0]
        if total_marks is None:
            total_marks = 0

        cursor.execute("SELECT studentnumber, workbookname FROM sessions WHERE sessionid = %s", [sessionid])
        session_row = cursor.fetchone()
        if not session_row:
            return
        studentid, workbookname = session_row
        courseid = workbookname[:8]
        tutid = workbookname[8:12]

        # Fixed total: sum of marks in question_md for this tutorial and course
        cursor.execute(
            """
            SELECT COALESCE(SUM(marks), 0)
            FROM question_md
            WHERE LOWER(question_tut) = LOWER(%s) AND LOWER(question_course) = LOWER(%s)
            """,
            [tutid, courseid]
        )
        total_available = cursor.fetchone()[0]
        if not total_available:
            total_available = 0

        # Build grade (percentage) and grade_report: "X% (A/B)"
        if total_available:
            percentage = round((float(total_marks) / float(total_available)) * 100, 1)
            grade_report = f"{percentage}% ({total_marks}/{total_available})"
        else:
            percentage = 0
            grade_report = f"N/A ({total_marks}/0)"

        cursor.execute("SELECT oyear FROM studentclassesnew WHERE studentid = %s AND courseid = %s", [studentid, courseid])
        sc_row = cursor.fetchone()
        if not sc_row:
            return
        oyear = sc_row[0]

        cursor.execute(
            "SELECT grade FROM studentgradesnew WHERE studentid = %s AND courseid = %s AND tutid = %s AND oyear = %s AND sessionid = %s",
            [studentid, courseid, tutid, oyear, sessionid]
        )
        exists = cursor.fetchone()
        if exists:
            cursor.execute(
                "UPDATE studentgradesnew SET grade = %s, grade_report = %s WHERE studentid = %s AND courseid = %s AND tutid = %s AND oyear = %s AND sessionid = %s",
                [percentage, grade_report, studentid, courseid, tutid, oyear, sessionid]
            )
        else:
            cursor.execute(
                "INSERT INTO studentgradesnew (studentid, courseid, tutid, oyear, grade, grade_report, sessionid) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [studentid, courseid, tutid, oyear, percentage, grade_report, sessionid]
            )