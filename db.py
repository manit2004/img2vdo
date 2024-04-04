import os
import psycopg2

conn = psycopg2.connect("postgresql://manitroy:hZoVrgVUlm5JV81h3rtraQ@issproject-4067.7s5.aws-ap-south-1.cockroachlabs.cloud:26257/img2vdo?sslmode=verify-full")
cur=conn.cursor()
cur.execute("SELECT now()")
res = cur.fetchall()
conn.commit()
print(res)