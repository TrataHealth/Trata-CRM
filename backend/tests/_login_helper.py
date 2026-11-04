import sys

import requests

B = sys.argv[1]


def login(phone, pwd):
    s = requests.Session()
    s.post(B + '/api/auth/send-otp', json={'phone': phone})
    t = s.post(B + '/api/auth/verify-otp', json={'phone': phone, 'otp': '123456'}).json()['temp_token']
    r = s.post(B + '/api/auth/login-password', json={'password': pwd}, headers={'Authorization': 'Bearer ' + t}).json()
    s.headers['Authorization'] = 'Bearer ' + (r.get('token') or r.get('access_token'))
    return s
