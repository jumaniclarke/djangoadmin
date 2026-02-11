from django.shortcuts import render
from django.views.decorators.cache import cache_page
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from .models import MyTable

# Create your views here.
#def display_table(request):
#    # Retrieve all records from MyTable using its primary key (works even if it's not named "id")
#    data = MyTable.objects.order_by('-pk')[:20]
#    # Pass the data to the template context
#    return render(request, 'myapp/display_table.html', {'table_data': data})
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

from django.db import connection
from django.template import RequestContext

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