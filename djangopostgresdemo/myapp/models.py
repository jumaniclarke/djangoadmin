from django.db import models

# Create your models here.

class MyTable(models.Model):
    sessionid = models.BigAutoField(primary_key=True)
    workbookname = models.CharField(max_length=50)
    worksheetname = models.CharField(max_length=50)
    studentnumber = models.CharField(max_length=10)
    inserttimestamp = models.DateTimeField(auto_now_add=True)
    computername = models.CharField(max_length=255)
    
    class Meta:
        managed = False
        db_table = 'session_stream'
        
# Note: the answers_stream table is queried directly in views using raw SQL
# because the original table may use a composite primary key (sessionid, questionid)
# and the database schema is managed externally. If you prefer an ORM model,
# add a surrogate primary key column in the DB or adjust this model to match
# the actual schema and set appropriate primary_key fields.

class AnswersTable(models.Model):
    sessionid = models.BigIntegerField(db_column='sessionid')
    questionid = models.CharField(max_length=50)
    answertext = models.TextField(blank=True, null=True)
    answerformula = models.TextField(blank=True, null=True)
    answervalue = models.FloatField(blank=True, null=True)
    markawarded = models.FloatField(blank=True, null=True)
    feedback = models.TextField(blank=True, null=True)
    chartdata = models.JSONField(blank=True, null=True)
    tabledata = models.JSONField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'answers_stream'