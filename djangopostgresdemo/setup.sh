#!/bin/bash
pip install -r requirements.txt
python -c "import nltk; nltk.download('wordnet')"
python -m spacy download en_core_web_sm
python manage.py migrate