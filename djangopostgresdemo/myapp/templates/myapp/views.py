from django.shortcuts import render, redirect
from django.views.decorators.cache import cache_page
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.views.decorators.http import require_POST
from django.contrib import messages
from .models import MyTable
from django.db import connection

# Create your views here.
@cache_page(60)  # Cache the view for 60 seconds
def display_table(request):
    filter_value = request.GET.get('filter_by', 'all')
    student = request.GET.get('student','').strip()
    qs = MyTable.objects.all()
    if filter_value in ('MAM1014F', 'MAM1022F', 'MAM1013F'):
        qs = qs.filter(workbookname__startswith=filter_value)
    # limit to required fields only and order once
    if student:
        qs = qs.filter(studentnumber__icontains=student)

    qs = qs.order_by('-sessionid').only('sessionid', 'workbookname', 'studentnumber', 'inserttimestamp', 'computername')

    paginator = Paginator(qs, 50)  # Show 50 records per page
    page_number = request.GET.get('page',1)
    try:
        page_obj = paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)
        
    return render(request, 'myapp/display_table.html', {
        'table_data': page_obj.object_list,
        'page_obj': page_obj,
        'filter_by': filter_value,
    })

def display_answers(request):
    # Accept session id via GET param `sessionid` or fall back to None
    sessionid = request.GET.get('sessionid')
    if not sessionid:
        return render(request, 'myapp/display_answers.html', {
            'answers': [],
            'error': 'No sessionid provided. Use ?sessionid=<id> to view answers.'
        })

    # Use raw SQL to query answers to avoid ORM primary-key issues
    with connection.cursor() as cur:
        cur.execute(
            '''SELECT sessionid, questionid, answertext, answerformula, answervalue,
                      markawarded, feedback, chartdata, tabledata
               FROM answers
               WHERE sessionid = %s
               ORDER BY questionid''', [sessionid]
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Always return all answers for the session; let JS handle questionid search
    return render(request, 'myapp/display_answers.html', {
        'answers': rows,
        'sessionid': sessionid,
    })




def mark_workbooks(request):
    from datetime import datetime
    from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
    courses = ['MAM1014F', 'MAM1022F', 'MAM1013F']
    tutorials = ['TUT1', 'TUT2']
    selected_course = request.POST.get('course') or request.GET.get('course', courses[0])
    selected_tutorial = request.POST.get('tutorial') or request.GET.get('tutorial', tutorials[0])
    workbookname = f"{selected_course}{selected_tutorial}.XLS"
    sessions = []
    with connection.cursor() as cur:
        cur.execute(
            "SELECT sessionid, studentnumber, inserttimestamp, computername FROM sessions WHERE workbookname = %s ORDER BY inserttimestamp DESC",
            [workbookname]
        )
        sessions = cur.fetchall()

    # Pagination
    page = request.GET.get('page', 1)
    paginator = Paginator(sessions, 100)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # Default date is today, but allow override via POST or GET
    date_str = request.POST.get('batch_date') or request.GET.get('batch_date')
    batch_date = None
    if date_str:
        try:
            batch_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            batch_date = None
    else:
        batch_date = datetime.now().date()

    # Handle POST for single marking and batch marking
    if request.method == 'POST':
        if 'sessionid' in request.POST:
            sessionid = request.POST.get('sessionid')
            if sessionid:
                from myapp.management.commands.marking import mark_answers_for_session
                mark_answers_for_session(int(sessionid))
                messages.success(request, f"Marking triggered for session {sessionid}.")
                return redirect(request.path + f"?course={selected_course}&tutorial={selected_tutorial}")
        elif 'mark_recent_batch' in request.POST:
            # Mark most recent submission per student for selected date
            with connection.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (studentnumber) sessionid, studentnumber, inserttimestamp
                    FROM sessions
                    WHERE workbookname = %s AND DATE(inserttimestamp) = %s
                    ORDER BY studentnumber, inserttimestamp DESC
                    """,
                    [workbookname, batch_date]
                )
                recent_sessions = cur.fetchall()
            from myapp.management.commands.marking import mark_answers_for_session
            marked = 0
            for session in recent_sessions:
                sessionid = session[0]
                mark_answers_for_session(int(sessionid))
                marked += 1
            messages.success(request, f"Marked {marked} most recent submissions for {batch_date}.")
            return redirect(request.path + f"?course={selected_course}&tutorial={selected_tutorial}&batch_date={batch_date}")

    return render(request, 'myapp/mark_workbooks.html', {
        'courses': courses,
        'tutorials': tutorials,
        'selected_course': selected_course,
        'selected_tutorial': selected_tutorial,
        'sessions': page_obj.object_list,
        'workbookname': workbookname,
        'batch_date': batch_date,
        'page_obj': page_obj,
        'paginator': paginator,
    })