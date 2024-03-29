"""
2017 VTHacks Submission - LetsGoEatAlready by Wes Jordan

This is a small webapp that I created to address my family's general inability to come to a consensus when it comes to 
    finding a place to eat. The way it works is that it searches restaurants near you based on the parameters you give it
    using the Google Places API and then returns exactly four places from you to choose. If you don't like one of the
    options displayed, you can simply click it away and another one will come back and take its place. 
    
    The goal of this application is to combat you or your group's dawdling indecisiveness by reducing your number of 
    options and make it easy to come to a decision when the only thing you can agree on is that you're all starving. It 
    also encourages visiting new places by selecting some that may be lesser known.
    
    The application works off of a Flask backend that serves and renders most of the page's UI using Jinja2 templates. 
    New places are added via AJAX requests using session verification, using info from Google's places API. Results from
    from the API are cached in Firebase in order to limit API calls.
"""

import os
from math import floor
from random import random

import googlemaps
from flask import Flask, render_template, request, send_from_directory, session, abort, jsonify, redirect, url_for, \
    flash

from server import gmaps_key, firebase, APP_STATIC, SESSION_KEY
from server.util import haversine

app = Flask(__name__, template_folder="templates", static_url_path='/static')
app.secret_key = SESSION_KEY

gmaps = googlemaps.Client(key=gmaps_key)

queues = {}


@app.route('/')
def index():
    return render_template("index.html")


@app.route('/search')
def start_search():
    sessid = os.urandom(8)
    session['sess_id'] = sessid
    init_success = init_session(sessid)

    if not init_success:
        flash("Invalid search location.")
        return redirect(url_for('index'))

    else:
        return render_template('search.html',
                               loc=request.args.get('address'),
                               radius=int(request.args.get('radius')) * 1600,
                               prefer=request.args.get('prefer'),
                               maxprice=int(request.args.get('maxprice')))


@app.route('/ajax/get_results')
def get_results():
    if 'sess_id' not in session:
        abort(403)

    num = int(request.args.get('num'))
    if num < 1:
        num = 1
    elif num > 4:
        num = 4

    queue = queues[session['sess_id']]
    resp = []
    for i in range(num):
        if len(queue) <= 5:
            if not get_more_results(): abort(410)

        try:
            index = low_random(0, len(queue))
            resp.append(queue[index])
            del queue[index]
        except IndexError:
            print("index %d, len %d" % (index, len(queue)))
            abort(500)

    return render_template("place.html", places=resp)


def get_more_results():
    print("Tried to get more results")

    if 'next_token' not in session or session['next_token'] is None:
        return False

    more_places = gmaps.places_nearby(location=None,
                                      page_token=session['next_token']
                                      )

    queues[session['sess_id']].append(more_places['results'])
    session['next_token'] = more_places['next_page_token'] if 'next_page_token' in more_places else None
    return True


def low_random(min, max):
    return floor(abs(random() - random()) * (1 + max - min) + min)


@app.route('/place-photo/<picture_ref>')
def place_photo(picture_ref):
    import urllib.request

    folder = APP_STATIC + '/place_photos/'
    filename = folder + picture_ref + '.jpg'
    if not os.path.isfile(filename):
        url = 'https://maps.googleapis.com/maps/api/place/photo?maxwidth=512&photoreference=%s&key=%s' % (picture_ref, gmaps_key)
        urllib.request.urlretrieve(url, filename)

    return send_from_directory(folder, picture_ref + '.jpg')


@app.route('/place_website/<place_id>')
def place_website(place_id):
    cached_result = firebase.get('cache/gmaps/details/' + str(place_id))
    if cached_result is not None:
        place_details = cached_result
    else:
        place_details = gmaps.place(place_id=place_id)
        firebase.push('cache/gmaps/details/' + str(place_id), place_details)

    place_details = place_details['result']

    if 'website' in place_details and len(place_details['website']) > 0:
        return redirect(place_details['website'])
    else:
        return redirect(place_details['url'])


def init_session(sess_id):
    cached_result = firebase.get('cache/gmaps/' + str(request.query_string))
    loc = request.args.get('address')
    prefer = request.args.get('prefer')
    radius = int(request.args.get('radius')) * 1600  # Convert miles to metres

    geo_res = gmaps.geocode(loc)
    if geo_res is None or len(geo_res) == 0:
        return False

    if cached_result is not None:
        places = cached_result
        print("Using firebase!")
    else:
        latlon = (geo_res[0]['geometry']['location']['lat'], geo_res[0]['geometry']['location']['lng'])
        places = gmaps.places_nearby(
            location=latlon,
            radius=radius if prefer == 'prominence' else None,
            rank_by=prefer,
            keyword='restaurant',
            max_price=int(request.args.get('maxprice'))
        )

        firebase.push('cache/gmaps/' + str(request.query_string), places)
        print("Using Gmaps!")

    for place in places['results']:
        place['distance'] = round(haversine(geo_res[0]['geometry']['location'], place['geometry']['location']), 1)

    global queues
    queues[sess_id] = places['results']

    session['next_token'] = places['next_page_token']
    return True


if __name__ == '__main__':
    app.run(debug=True)
