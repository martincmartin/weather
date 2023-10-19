import urllib.request
import json
from datetime import timedelta
import datetime
import time
from PIL import Image, ImageDraw, ImageFont
import math
import sys
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler
from enum import Enum
import os
import shutil
import subprocess
import threading
import time
import argparse


# The screen is 800 x 480.


# Uses weather.gov, see here:
#
# https://weather-gov.github.io/api/general-faqs
#
# To get current weather conditions from OpenWeatherMap:
#
# https://api.openweathermap.org/data/2.5/weather?lat=[your-latitutde]&lon=[your-longitude]&appid=[your-app-id]


# A probability of precipitation greather than this will show the raining
# clothing icon.
RAINING_THRESHOLD = 33.333

PRECIPITATION_GREY = (255 * 2) // 3

# Could go lighter.
AFTERNOON_GREY = (PRECIPITATION_GREY + 256) // 2

AFTERNOON_PRECIPITATION_GREY = PRECIPITATION_GREY * AFTERNOON_GREY // 255

TEMPERATURE_BOX = (800 - 256, 25, 800 - 128, 25 + 128)
ICON_BOX = (800 - 128, 25, 800, 25 + 128)

# Aligned to the bottom right.  Width equals sky icon plus temp: 256. For
# height, subtract sky icon = temp = 128, plus a 25 pixel border above those.

MORNING_CLOTHING_BOX = (800 - 256, 128 + 25, 800 - 128, 480)
AFTERNOON_CLOTHING_BOX = (800 - 128, 128 + 25, 800, 480)
CLOTHING_BOX = (800 - (128 + 64), 128 + 25, 800 - 64, 480)

GAP_BETWEEN_GRAPH_AND_LABELS = 10

# If using rtl_433 to read a physical, outdoor temperature sensor, only listen
# to the model, ID and channel specified here.
RTL_433_MODEL = "LaCrosse-TX141THBv2"
RTL_433_ID = 84
RTL_433_CHANNEL = 0

# Set current directory to the directory containing this script.
os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))


OPENWEATHERMAP_APPID = os.getenv("OPENWEATHERMAP_APPID")
if not OPENWEATHERMAP_APPID:
    print(
        "Please supply OpenWeatherMap app ID in the environment variable OPENWEATHERMAP_APPID",
        file=sys.stderr,
    )
    sys.exit(1)

parser = argparse.ArgumentParser(
    prog="weather",
    description="Serve weather dashboard for invisible-computer e-ink display",
)
parser.add_argument("latitude", type=float)
parser.add_argument("longitude", type=float)
args = parser.parse_args()

LATITUDE = args.latitude
LONGITUDE = args.longitude


def scale_to_fit(image, box):
    width = box[2] - box[0]
    height = box[3] - box[1]
    factor = min(width / image.size[0], height / image.size[1])
    return image.resize(
        (int(round(image.size[0] * factor)), int(round(image.size[1] * factor)))
    )


# Used to communicate between the main thread and the thread running the RTL_433
# program, which receives temperature (and humidity, not used) from the LaCrosse
# outdoor temperature sensor.
class LocalWeather:
    def __init__(self):
        self.lock = threading.Lock()
        self.time = datetime.datetime(2000, 1, 1)
        self.temperature = 999
        self.humidity = 999
        self.battery_ok = True

    def set(self, time, temperature, humidity, battery_ok):
        with self.lock:
            self.time = time
            self.temperature = temperature
            self.humidity = humidity
            self.battery_ok = battery_ok


local_weather = LocalWeather()


def rtl_433_thread(local_weather: LocalWeather):
    try:
        rtl_433_loop(local_weather)
    except Exception as e:
        print(f'***** RTL 433 thread had exception "{str(e)}"')
    except:
        print(f"***** Caught unknown exception in RTL 433 thread! {sys.exc_info()[0]}")

    print("*****  rtl_433 thread ended!", flush=True)
    sys.exit(2)


def rtl_433_loop(local_weather: LocalWeather):
    subprocess.run(["pkill", "rtl_433"])
    while subprocess.run(["pgrep", "rtl_433"]).returncode == 0:
        print("***** rtl_433 still running, sleeping.")
        time.sleep(1)

    proc = subprocess.Popen(
        [have_rtl_433, "-F", "json", "-M", "level"],
        shell=False,
        bufsize=1,
        text=True,
        stdout=subprocess.PIPE,
    )
    for line in proc.stdout:
        line = line.strip()
        print(line, flush=True)
        parsed = json.loads(line)
        if (
            parsed["model"] == RTL_433_MODEL
            and parsed["id"] == RTL_433_ID
            and parsed["channel"] == RTL_433_CHANNEL
        ):
            local_weather.set(
                datetime.datetime.fromisoformat(parsed["time"]),
                parsed["temperature_C"] * 1.8 + 32,
                parsed["humidity"],
                parsed["battery_ok"] == 1,
            )


have_rtl_433 = shutil.which("rtl_433")
print(f"{have_rtl_433=}")
if have_rtl_433:
    thread = threading.Thread(target=rtl_433_thread, args=(local_weather,))
    thread.start()


class Period:
    def __init__(self, period_dict, timezone):
        self.start = datetime.datetime.fromisoformat(
            period_dict["startTime"]
        ).astimezone(timezone)
        self.end = datetime.datetime.fromisoformat(period_dict["endTime"]).astimezone(
            timezone
        )
        self.mid = self.start + (self.end - self.start) / 2
        self.temp = period_dict["temperature"]
        self.precipitation = period_dict["probabilityOfPrecipitation"]["value"] or 0

    def __repr__(self):
        return f"{self.start} to {self.end} temp: {self.temp}"


class Forecast:
    def __init__(self, isDaytime, shortForecast: str, periods, daily):
        self.isDaytime = isDaytime
        self.shortForecast = shortForecast
        self.periods = periods
        self.daily = daily


def load_icon(fname, box):
    return scale_to_fit(Image.open(fname).convert("L"), box)


class TemperatureBand(Enum):
    HOT = 0
    WARM = 1
    COOL = 2
    COLD = 3


clothing_not_raining = {
    member: load_icon(f"clothing-icons/boy-{member.name.lower()}.png", CLOTHING_BOX)
    for member in TemperatureBand
}

clothing_raining = {
    member: load_icon(
        f"clothing-icons/boy-{member.name.lower()}-rain.png", CLOTHING_BOX
    )
    for member in TemperatureBand
}


def get_clothing(temperature, is_raining):
    # Should this take into account sunny vs cloudy?  Direct sun will definitely
    # feel warmer than the measured or forecast temperatures, which are always
    # in the shade.
    clothing = clothing_raining if is_raining else clothing_not_raining
    if temperature < 39.5:
        return clothing[TemperatureBand.COLD]
    elif temperature < 70:
        return clothing[TemperatureBand.COOL]
    elif temperature < 79.5:
        return clothing[TemperatureBand.WARM]
    else:
        return clothing[TemperatureBand.HOT]


class Cloudiness(Enum):
    CLOUDY = 0
    MOSTLY_CLOUDY = 1
    MOSTLY_CLEAR = 2
    CLEAR = 3


class DayNight(Enum):
    DAY = 0
    NIGHT = 1


class Precipitation(Enum):
    NONE = 0
    DRIZZLE = 1
    LIGHT_RAIN = 2
    RAINY = 3
    THUNDERSTORMS = 4
    SNOW = 5


def weather_icon_fname(
    day_night: DayNight,
    cloudiness: Cloudiness,
    precipitation: Precipitation,
    windy: bool,
):
    if precipitation in [
        Precipitation.NONE,
        Precipitation.THUNDERSTORMS,
        Precipitation.SNOW,
    ]:
        windy = False

    if precipitation != Precipitation.NONE:
        if cloudiness != Cloudiness.CLOUDY:
            cloudiness = Cloudiness.MOSTLY_CLOUDY

    if day_night == DayNight.NIGHT and cloudiness == Cloudiness.MOSTLY_CLEAR:
        cloudiness = Cloudiness.MOSTLY_CLOUDY

    day_night_string = (
        "" if cloudiness == Cloudiness.CLOUDY else (day_night.name.lower() + " ")
    )
    cloudiness_string = cloudiness.name.lower().replace("_", " ")
    precipitation_string = (
        (" " + precipitation.name.lower().replace("_", " "))
        if precipitation != Precipitation.NONE
        else ""
    )
    windy_string = " windy" if windy else ""

    return day_night_string + cloudiness_string + precipitation_string + windy_string


def load_weather_icons():
    weather_icons = {}
    for day_night in DayNight:
        for cloudiness in Cloudiness:
            for precipitation in Precipitation:
                for windy in [True, False]:
                    fname = weather_icon_fname(
                        day_night, cloudiness, precipitation, windy
                    )
                    if fname not in weather_icons:
                        weather_icons[fname] = load_icon(
                            f"weather-icons/{fname}.png",
                            ICON_BOX,
                        )
    return weather_icons


weather_icons = load_weather_icons()


def fetch_json(url):
    while True:
        try:
            # Send an HTTP GET request to the URL
            with urllib.request.urlopen(url) as response:
                if response.status == 200:
                    # Read the response data and decode it as JSON
                    return json.loads(response.read().decode("utf-8"))
                else:
                    raise Exception(f"request failed with status {response.status}")
        except Exception as e:
            print(f"Received error {e}, trying again in 6 seconds.")
        time.sleep(6)


def get_forecast(latitude, longitude):
    # To do: replace weather.gov with OpenWeatherMap.
    url = f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}"

    points = fetch_json(url)
    properties = points["properties"]
    timezone = ZoneInfo(properties["timeZone"])

    # According to an answer to my question at
    # https://github.com/weather-gov/api/discussions/660
    #
    # "/gridpoints is the raw forecast data produced by the WFO, keyed by
    # weather element /gridpoints/.../forecast is the processed version of
    # /gridpoints, ready for publication on a forecast site, keyed by time"
    #
    # https://en.wikipedia.org/wiki/ISO_8601#Durations
    #
    forecast = fetch_json(properties["forecast"])
    first_period = forecast["properties"]["periods"][0]
    isDaytime = first_period["isDaytime"]
    shortForecast = first_period["shortForecast"]

    forecastHourly = fetch_json(properties["forecastHourly"])

    periods_json = forecastHourly["properties"]["periods"]
    periods = [Period(period, timezone) for period in periods_json]
    if periods[0].end < datetime.datetime.now(datetime.timezone.utc):
        print("Trimming first period, since the end has already passed.")
        periods = periods[1:]

    owm_data = owm.get()

    return Forecast(isDaytime, shortForecast, periods, owm_data["daily"])


# We get 1,000 calls a day for free, but calling once a minute would be 1,440
# calls.  So, we cache.  OWM is updated every 10 minutes, so we query once every
# 5 minutes, so that our display is at most 5 minutes stale.  That's 288 calls
# per day.
class OpenWeatherMap:
    def __init__(self, latitude, longitude, appid):
        self.latitude = latitude
        self.longitude = longitude
        self.appid = appid
        self.last_time = None
        self.last_data = None

    def get(self):
        current_time = time.monotonic()
        if self.last_time is None or current_time > self.last_time + 5 * 60:
            url = f"https://api.openweathermap.org/data/3.0/onecall?lat={self.latitude}&lon={self.longitude}&exclude=minutely&units=imperial&appid={self.appid}"
            self.last_data = fetch_json(url)
            self.last_time = current_time
        return self.last_data


owm = OpenWeatherMap(LATITUDE, LONGITUDE, OPENWEATHERMAP_APPID)


# Returns a 2-element tuple.  First is a bool, whether or not it's currently
# raining.  Second is current temperature.
def get_current(latitude, longitude):
    # See https://openweathermap.org/current for explanation.
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={latitude}&lon={longitude}&appid={OPENWEATHERMAP_APPID}&units=imperial"

    result = fetch_json(url)

    # See https://openweathermap.org/weather-conditions
    weather_id = result["weather"][0]["id"]

    return (weather_id < 600, result["main"]["temp"])


def round_up_to_next_6_hours(input_datetime):
    # Calculate the number of hours to the next multiple of 6
    hours_to_next_6 = (6 - input_datetime.hour % 6) % 6

    timedelta_to_next_6 = timedelta(hours=hours_to_next_6)

    # Round up the input datetime to the next multiple of 6 hours
    rounded_datetime = input_datetime + timedelta_to_next_6
    return rounded_datetime.replace(minute=0, second=0, microsecond=0)


def round_to_next_day(input_datetime):
    truncated = input_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
    if truncated < input_datetime:
        return truncated + timedelta(days=1)
    else:
        return truncated


def plot_graph(periods, image, rect):
    multiday = len(periods) >= 48

    min_temp = min(p.temp for p in periods)
    max_temp = max(p.temp for p in periods)

    low_temp = math.floor(min_temp / 5) * 5
    high_temp = math.ceil(max_temp / 5) * 5

    min_time = min(p.start for p in periods).timestamp()
    max_time = max(p.end for p in periods).timestamp()

    draw = ImageDraw.Draw(image)
    font_size = (rect[3] - rect[1]) // 7
    font = ImageFont.truetype("Pillow/Tests/fonts/DejaVuSans.ttf", font_size)

    # This code for adjusting for text size is only approximate, so in practice,
    # when you change font size, you still need to adjust the rect parameter
    # passed into plot_graph().  Oh well.

    y_label_bbox = font.getbbox("99")
    y_label_width = y_label_bbox[2] - y_label_bbox[0]

    x_label_bbox = font.getbbox("Sun")
    x_label_height = x_label_bbox[3] - x_label_bbox[1]

    graph_left = rect[0] + y_label_width
    graph_right = rect[2]
    graph_top = rect[1]
    graph_bottom = rect[3] - x_label_height - GAP_BETWEEN_GRAPH_AND_LABELS

    # Map low_temp to bottom of rect, and high_temp to top.
    def temp_to_y(temp):
        return (temp - low_temp) / (high_temp - low_temp) * (
            graph_top - graph_bottom
        ) + graph_bottom

    def to_x(time):
        time = time.timestamp()
        assert time >= min_time
        assert time <= max_time
        x = (time - min_time) / (max_time - min_time) * (
            graph_right - graph_left
        ) + graph_left
        return x

    #####  Draw the % precipitation polygon.
    precip_polygon = [(graph_left, graph_bottom)]
    for period in periods:
        y = period.precipitation / 100.0 * (graph_top - graph_bottom) + graph_bottom
        precip_polygon += [(to_x(period.start), y), (to_x(period.end), y)]

    precip_polygon.append((graph_right, graph_bottom))
    draw.polygon(precip_polygon, fill=PRECIPITATION_GREY)

    #####  Draw horizontal lines & labels for temperatures.
    # Should probably decide between every 10 degrees and every 5 degress based
    # on e.g. whatever gives closest to 5 lines.
    for temp in range(low_temp, high_temp + 1, 10):
        y = temp_to_y(temp)
        draw.line((graph_left, y, graph_right, y), fill=128)
        draw.text((graph_left - 3, y), str(temp), font=font, fill=0, anchor="rm")

    #####  Draw vertical lines & labels for times
    start_datetime = min(p.start for p in periods)
    end_datetime = max(p.end for p in periods)
    if multiday:
        this_datetime = round_to_next_day(start_datetime)

        while this_datetime < end_datetime:
            x = to_x(this_datetime)
            draw.line((x, graph_top, x, graph_bottom), fill=128)

            text_datetime = this_datetime + timedelta(hours=12)
            if text_datetime < end_datetime:
                draw.text(
                    (to_x(text_datetime), graph_bottom + GAP_BETWEEN_GRAPH_AND_LABELS),
                    this_datetime.strftime("%a"),
                    font=font,
                    fill=0,
                    anchor="ma",
                )
            this_datetime += timedelta(days=1)
    else:
        this_datetime = round_up_to_next_6_hours(start_datetime)

        while this_datetime < end_datetime:
            x = to_x(this_datetime)

            if this_datetime.hour == 0:
                draw.line((x, graph_top, x, graph_bottom), fill=128)

            if this_datetime.hour == 12:
                text = "noon"
            elif this_datetime.hour == 0:
                text = this_datetime.strftime("%a")
            else:
                text = this_datetime.strftime("%-I%p").lower()

            draw.text(
                (x, graph_bottom + GAP_BETWEEN_GRAPH_AND_LABELS),
                text,
                font=font,
                fill=0,
                anchor="ma",
            )

            this_datetime += timedelta(hours=6)

    # Draw the actual temperatures.
    if multiday:
        xy = [(to_x(period.mid), temp_to_y(period.temp)) for period in periods]
        draw.line(xy, fill=0, width=1)
    else:
        for period in periods:
            y = temp_to_y(period.temp)
            left = to_x(period.start)
            right = to_x(period.end)

            if period.start.hour == 15:
                draw.rectangle(
                    (left, graph_top, right, graph_bottom - 1),
                    fill=AFTERNOON_GREY,
                )
                if period.precipitation > 0:
                    precipitation_y = (
                        period.precipitation / 100.0 * (graph_top - graph_bottom)
                        + graph_bottom
                    )
                    draw.rectangle(
                        (left, precipitation_y, right, graph_bottom - 1),
                        fill=AFTERNOON_PRECIPITATION_GREY,
                    )

            draw.line(
                (to_x(period.start), y, to_x(period.end), y),
                fill=0,
                width=3,
            )


def draw_icon(forecast, image, left, top):
    today = forecast.daily[0]
    # I would like to include the description text somewhere, but it can be
    # quite long, e.g. "thunderstorm with heavy drizzle", and I don't want to
    # give up screen real estate anywhere for that.  Maybe across the top, right
    # justified?
    print(json.dumps(today["weather"][0]))
    weather_id = today["weather"][0]["id"]

    # First figure out precipitation.
    # See https://openweathermap.org/weather-conditions#Weather-Condition-Codes-2
    if weather_id >= 700:
        precipitation = Precipitation.NONE
    elif weather_id >= 600:
        precipitation = Precipitation.SNOW
    elif weather_id >= 500:
        if weather_id == 500 or weather_id == 520:
            precipitation = Precipitation.LIGHT_RAIN
        elif weather_id == 511:
            precipitation = Precipitation.SNOW
        else:
            precipitation = Preciptation.RAINY
    elif weather_id >= 300:
        precipitation = Precipitation.DRIZZLE
    else:
        precipitation = Precipitation.THUNDERSTORMS

    # I read somewhere that 20 mph is the threshold for "windy".
    windy = today["wind_speed"] > 20
    print(f'wind_speed = {today["wind_speed"]}, clouds = {today["clouds"]}')

    if today["clouds"] <= 25:
        cloudiness = Cloudiness.CLEAR
    elif today["clouds"] <= 50:
        cloudiness = Cloudiness.MOSTLY_CLEAR
    elif today["clouds"] <= 75:
        cloudiness = Cloudiness.MOSTLY_CLOUDY
    else:
        cloudiness = Cloudiness.CLOUDY

    fname = weather_icon_fname(
        DayNight.DAY if forecast.isDaytime else DayNight.NIGHT,
        cloudiness,
        precipitation,
        windy,
    )
    icon = weather_icons[fname]

    image.paste(icon, box=(ICON_BOX[0], ICON_BOX[1]))


# Paste an image into another image, centering it in the specified box.
def paste_image(image, small_image, box):
    image.paste(
        small_image,
        box=(
            (box[0] + box[2] - small_image.size[0]) // 2,
            (box[1] + box[3] - small_image.size[1]) // 2,
        ),
    )


def get_image():
    image = Image.new("L", (800, 480), 255)
    draw = ImageDraw.Draw(image)

    forecast = get_forecast(LATITUDE, LONGITUDE)

    current_raining, owm_temperature = get_current(LATITUDE, LONGITUDE)
    print(f"OWM current temp: {owm_temperature}")

    ##### Get the current temperature.  Should probably be made into a function.
    current_temperature = None
    with local_weather.lock:
        battery_ok = local_weather.battery_ok
        if local_weather.time > datetime.datetime.now() - timedelta(minutes=5):
            current_temperature = local_weather.temperature

    if not have_rtl_433:
        current_temperature = forecast.periods[0].temp

    if current_temperature is not None:
        text = str(round(current_temperature)) + "\N{DEGREE SIGN}"
        current_icon = get_clothing(current_temperature, current_raining)
    else:
        current_icon = None
        text = "--"

    ##### Get the afternoon temperature when kids come home from school.
    now = datetime.datetime.now(datetime.timezone.utc).astimezone()
    # This doesn't take into account daylight saving, and so will do the wrong
    # thing between midnight and two am, twice a year.  I can live with that.
    school = now.replace(hour=15, minute=40, second=0, microsecond=0)
    school_periods = [
        p
        # Skip the first period, since if they're comming home from school
        # within the hour, we want the actual temperature & rain, not forecast.
        for p in forecast.periods[1:]
        if p.start < school and p.end > school
    ]
    school_icon = None
    if school_periods:
        assert len(school_periods) == 1
        school_icon = get_clothing(
            school_periods[0].temp, school_periods[0].precipitation > RAINING_THRESHOLD
        )

    ##### Now draw the two clothing icons
    if current_icon is None:
        if school_icon is not None:
            paste_image(image, school_icon, AFTERNOON_CLOTHING_BOX)
    else:
        if school_icon is None or current_icon == school_icon:
            paste_image(image, current_icon, CLOTHING_BOX)
        else:
            paste_image(image, current_icon, MORNING_CLOTHING_BOX)
            paste_image(image, school_icon, AFTERNOON_CLOTHING_BOX)

    font = ImageFont.truetype("Pillow/Tests/fonts/DejaVuSans.ttf", 64)

    if battery_ok:
        draw.text(
            (
                (TEMPERATURE_BOX[0] + TEMPERATURE_BOX[2]) // 2,
                (TEMPERATURE_BOX[1] + TEMPERATURE_BOX[3]) // 2,
            ),
            text,
            font=font,
            fill=0,
            anchor="mm",
        )

        draw_icon(forecast, image, 544, 25)
    else:
        draw.multiline_text(
            (image.size[0] - 128, 89), "Battery\nLow", font=font, fill=0, anchor="mm"
        )
    periods = forecast.periods

    # Plot graph for next 24 hours.
    plot_graph(periods[0:24], image, (20, 25, 543, 220))
    # Plot graph for the coming week.
    plot_graph(periods, image, (20, 265, 543, 460))

    return image


class WeatherHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/weather.bmp":
            print("Someone wants to know whether the weather is wetter.", flush=True)
            self.send_response(200)
            self.send_header("Content-type", "image/bmp")
            self.end_headers()
            image = get_image().convert("1")
            image.save(self.wfile, format="BMP")
        else:
            print("Got some other GET request.", flush=True)
            self.send_response(404)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Not found.</title></head>")
            self.wfile.write(b"<body><p>Don't hack me go away.</p>")
            self.wfile.write(b"</body></html>")


def run_http_server():
    server_address = ("", 8998)
    print("Launching server.", flush=True)
    httpd = HTTPServer(server_address, WeatherHTTPRequestHandler)
    print("Listening.", flush=True)
    httpd.serve_forever()


run_http_server()
