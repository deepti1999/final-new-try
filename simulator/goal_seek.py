def goal_seek(func, x0, x1, target=0.0, tol=1e-6, max_iter=30):
    """
    Secant-method GoalSeek.
    func: callable that returns the measured value for the current guess.
    x0, x1: starting guesses (x1 should differ from x0 to set direction).
    target: desired function value.
    Returns the best x found (last iterate) even if tolerance not reached.
    """
    f0 = func(x0) - target
    if abs(f0) < tol:
        return x0

    # Avoid zero step by nudging x1 if identical
    if x1 == x0:
        x1 = x0 * 1.05 if x0 != 0 else 1.0

    f1 = func(x1) - target

    for _ in range(max_iter):
        if abs(f1) < tol:
            return x1

        denominator = (f1 - f0)
        if abs(denominator) < 1e-12:
            break  # avoid divide-by-zero; return best-so-far

        x2 = x1 - f1 * (x1 - x0) / denominator

        x0, f0 = x1, f1
        x1, f1 = x2, func(x2) - target

    return x1
