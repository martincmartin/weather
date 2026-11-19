"""The phase of the moon at a given time, from the positions of the Sun and the
Moon.

The formulas are the low-precision ones from Jean Meeus, "Astronomical
Algorithms" (chapters 25 and 47): the largest periodic terms only. The phase is
accurate to about 0.003 of a lunation (1 degree of elongation), much less than
one step of the 30 moon images.
"""

import datetime
import math

J2000 = datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.UTC)


def phase(time: datetime.datetime) -> float:
    """The fraction of the lunation at time: 0 is new moon, 0.25 first quarter,
    0.5 full moon, 0.75 last quarter. time must have a time zone."""
    if time.tzinfo is None:
        raise ValueError("phase() needs a time with a time zone")
    days = (time - J2000).total_seconds() / 86400

    def angle(at_j2000: float, degrees_per_day: float) -> float:
        return math.radians((at_j2000 + degrees_per_day * days) % 360)

    sun_mean_longitude = angle(280.460, 0.9856474)
    sun_mean_anomaly = angle(357.528, 0.9856003)
    moon_mean_longitude = angle(218.316, 13.176396)
    moon_mean_anomaly = angle(134.963, 13.064993)
    moon_mean_elongation = angle(297.850, 12.190749)
    moon_argument_of_latitude = angle(93.272, 13.229350)

    sun_longitude = (
        sun_mean_longitude
        + math.radians(1.915) * math.sin(sun_mean_anomaly)
        + math.radians(0.020) * math.sin(2 * sun_mean_anomaly)
    )
    moon_longitude = moon_mean_longitude + math.radians(
        6.289 * math.sin(moon_mean_anomaly)
        + 1.274 * math.sin(2 * moon_mean_elongation - moon_mean_anomaly)
        + 0.658 * math.sin(2 * moon_mean_elongation)
        + 0.214 * math.sin(2 * moon_mean_anomaly)
        - 0.186 * math.sin(sun_mean_anomaly)
        - 0.114 * math.sin(2 * moon_argument_of_latitude)
    )
    return ((moon_longitude - sun_longitude) / (2 * math.pi)) % 1
