import os
from supabase import create_client, Client

url: str = "https://safsghcjddrtiyqpyxqe.supabase.co"
key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNhZnNnaGNqZGRydGl5cXB5eHFlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM3MDAwMzIsImV4cCI6MjA1OTI3NjAzMn0.cYwf9w1HITybEngQXvXfLDQd1W7mcbkkDq-acsirlFs"
supabase: Client = create_client(url, key)
print(supabase)