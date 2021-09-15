import math

MULTIPLES = ["B", "k{}B", "M{}B", "G{}B", "T{}B", "P{}B", "E{}B", "Z{}B", "Y{}B"]


def human_bytes(sz, binary=True, precision=2):
    base = 1024 if binary else 1000
    multiple = math.trunc(math.log2(sz) / math.log2(base))
    value = sz / math.pow(base, multiple)
    suffix = MULTIPLES[multiple].format("i" if binary else "")
    return f"{value:.{precision}f} {suffix}"

# def HumanDate(date):
