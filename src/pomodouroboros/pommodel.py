"""
What do I want in here?

    - in a GUI I need to subscribe to updates

    - I need to be able to serialize and load the whole state of the world at
      any given time

        - state being:

            - stated intentions, including the current one

            - pass/fail status
"""
from __future__ import annotations
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, Sequence, Protocol, List, Union
from datetime import datetime, timedelta, date, time, tzinfo
from enum import Enum

from dateutil.tz import tzlocal


class IntentionResponse(Enum):
    """
    What can happen when you set an intetnion
    """

    CanBeSet = WasSet = "WasSet"
    # It was set!
    OnBreak = "OnBreak"
    # You can't set an intention on a break.
    TooLate = "TooLate"
    # You're beyond the grace period for this pomodoro.
    AlreadySet = "AlreadySet"
    # You can only set the intention once.


class PomObserver(Protocol):
    """
    Protocol that specifies interesting events that can happen inside a L{Day}.
    """

    def breakStarting(self, startingBreak: Break) -> None:
        """
        A break is starting.
        """

    def pomodoroStarting(self, day: Day, startingPomodoro: Pomodoro) -> None:
        """
        A pomodoro is starting; time to express an intention.
        """

    def elapsedWithNoIntention(self, pomodoro: Pomodoro) -> None:
        """
        A pomodoro completed, but no intention was specified.
        """

    def progressUpdate(
        self,
        interval: Interval,
        percentageElapsed: float,
        canSetIntention: IntentionResponse,
    ) -> None:
        """
        Some time has elapsed on the given interval, and it's now
        percentageElapsed% done.  canSetIntention tells you the likely outcome
        of setting the intention.
        """

    def dayOver(self):
        """
        The day is over, so there will be no more intervals.
        """


class IntentionSuccess(Enum):
    Achieved = "Achieved"
    "The goal described in the intention is finished."
    Focused = "Focused"
    "Good focus during the pomodoro, but the goal was not complete."
    Distracted = "Distracted"
    "Distracted during the pomodoro; not great progress."
    NeverEvaluated = "NeverEvaluated"
    "The deadline for evaluating this pom expired without an evaluation."


@dataclass
class Intention:
    description: str
    "A brief description of the intent of this pomodoro."
    wasSuccessful: Optional[Union[bool, IntentionSuccess]]
    """
    Was this pomodoro successful?  None if it's not complete yet.  True and
    False are legacy values, newer pomodoros should be set to an
    IntentionSuccess.
    """

    @property
    def isComplete(self) -> bool:
        return self.wasSuccessful is not None


@dataclass
class Pomodoro(object):
    """
    An interval of time that occurs during a day.
    """

    intention: Optional[Intention]
    "The intention, if one was specified."
    startTime: datetime
    endTime: datetime


@dataclass
class Score(object):
    """
    The score for a given day.
    """

    hits: Decimal
    "Points scored by the player."
    misses: Decimal
    "Potential points lost"
    unevaluated: Decimal
    "Evaluations which are still possible, but haven't been performed yet"
    remaining: Decimal
    "Intervals remaining that haven't been scored yet."


@dataclass
class Break:
    """
    A break; no goal, just chill.
    """

    startTime: datetime
    endTime: datetime


Interval = Union[Pomodoro, Break]


class DayOfWeek(Enum):
    monday = 0
    tuesday = 1
    wednesday = 2
    thursday = 3
    friday = 4
    saturday = 5
    sunday = 6


def isWeekend(aDate: date) -> bool:
    """
    Is the given day a weekend day?
    """
    return DayOfWeek(aDate.weekday()) in (DayOfWeek.saturday, DayOfWeek.sunday)


POINTS_LOOKUP = {
    None: (Decimal("0.1"), Decimal("1.0")),
    True: (Decimal("1.0"), Decimal("0.0")),
    False: (Decimal("0.25"), Decimal("1.0")),
    IntentionSuccess.Achieved: (Decimal("1.25"), Decimal("0.0")),
    IntentionSuccess.Focused: (Decimal("1.0"), Decimal("0.0")),
    IntentionSuccess.Distracted: (Decimal("0.25"), Decimal("1.0")),
    IntentionSuccess.NeverEvaluated: (Decimal("0.1"), Decimal("1.0")),
}


@dataclass
class Day(object):
    """
    A day is a collection of pomodoros that occur.
    """

    startTime: datetime
    "The time at which the day's set of pomodoros begins."
    endTime: datetime
    "The time at which the day's set of pomodoros ends."
    pendingIntervals: List[Interval]
    "Intervals which have not yet elapsed, and are not complete."
    elapsedIntervals: List[Interval]
    "Intervals which have fully elapsed."
    lastUpdateTime: datetime
    "When was this Day last updated?"
    intentionGracePeriod: timedelta

    def score(self) -> Score:
        """
        Evaluate the score of the current day.
        """
        result = Score(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
        elapsed = [
            interval
            for interval in self.elapsedIntervals
            if isinstance(interval, Pomodoro)
        ]
        pending = [
            interval
            for interval in self.pendingIntervals
            if isinstance(interval, Pomodoro)
        ]
        elapsed, grace = elapsed[:-1], elapsed[-1:]
        for stillPossibleToEvaluate in grace:
            if (
                stillPossibleToEvaluate.intention is not None
                and stillPossibleToEvaluate.intention.wasSuccessful is None
            ):
                result.unevaluated += 1
            else:
                elapsed.append(stillPossibleToEvaluate)

        if pending:
            # Did we already evaluate our currently-executing pom?
            current = pending[0]
            if (
                current.intention is not None
                and current.intention.wasSuccessful is not None
            ):
                # Treat it as completed if so.
                elapsed.append(pending.pop(0))

        for each in elapsed:
            if not isinstance(each, Pomodoro):
                # Breaks don't affect score.
                continue
            if each.intention is None:
                result.misses += Decimal("1.0")
                continue
            hits, misses = POINTS_LOOKUP[each.intention.wasSuccessful]
            result.hits += hits
            result.misses += misses
        result.remaining = Decimal(len(pending))
        return result

    @classmethod
    def new(
        cls,
        startTimeOfDay: Optional[time] = None,
        endTimeOfDay: Optional[time] = None,
        day: date = date.today(),
        timezone: tzinfo = tzlocal(),
        longBreaks: Optional[Sequence[int]] = None,
        pomodoroLength: timedelta = timedelta(minutes=25),
        breakLength: timedelta = timedelta(minutes=5),
        intentionGracePeriod: timedelta = timedelta(minutes=4),
    ) -> Day:
        """
        Create a new day filled with pomodoros.
        """
        if (
            isWeekend(day)
            and startTimeOfDay is None
            and endTimeOfDay is None
            and longBreaks is None
        ):
            # It might be nicer to have a 'configuration' object with all these
            # attributes so that we could supply one for weekdays and one for
            # weekends rather than this "you didn't pass any args" heuristic
            startTimeOfDay = time(0)
            endTimeOfDay = time(0)
            longBreaks = ()
        else:
            if startTimeOfDay is None:
                startTimeOfDay = time(9)
            if endTimeOfDay is None:
                endTimeOfDay = time(18)
            if longBreaks is None:
                longBreaks = (7, 8)  # 1 hour (2-pom) break for noon lunch.
        startTime = datetime.combine(day, startTimeOfDay, timezone)
        endTime = datetime.combine(day, endTimeOfDay, timezone)
        currentTime = startTime
        intervals: List[Interval] = []
        pomCount = 0
        longBreakStart = None
        while currentTime < endTime:
            pomStart = currentTime
            currentTime += pomodoroLength
            pomEnd = breakStart = currentTime
            currentTime += breakLength
            breakEnd = currentTime
            pomCount += 1
            if pomCount in longBreaks:
                # Collapse long breaks into a contiguous thing
                longBreakContinues = (pomCount + 1) in longBreaks
                if longBreakStart is None:
                    longBreakStart = pomStart
                if not longBreakContinues:
                    # end of long break
                    intervals.append(Break(longBreakStart, breakEnd))
                    longBreakStart = None
            else:
                intervals.append(Pomodoro(None, pomStart, pomEnd))
                intervals.append(Break(breakStart, breakEnd))
        return cls(
            startTime, endTime, intervals, [], startTime, intentionGracePeriod
        )

    @classmethod
    def forTesting(cls) -> Day:
        """
        Create a test day that starts around now and goes real fast.
        """
        startTime = datetime.now(tz=tzlocal()) + timedelta(seconds=15)
        return cls.new(
            startTimeOfDay=startTime.time(),
            endTimeOfDay=(startTime + timedelta(minutes=3)).time(),
            longBreaks=[],
            pomodoroLength=timedelta(seconds=30),
            breakLength=timedelta(seconds=15),
            intentionGracePeriod=timedelta(seconds=20),
        )

    def expressIntention(
        self, currentTime: datetime, description: str
    ) -> IntentionResponse:
        """
        UIs should call this when the user decides what the current pomodoro is
        about.
        """
        if not self.pendingIntervals:
            return IntentionResponse.OnBreak
        currentInterval = self.pendingIntervals[0]
        if isinstance(currentInterval, Break):
            return IntentionResponse.OnBreak
        elif isinstance(currentInterval, Pomodoro):
            if currentInterval.intention is not None:
                return IntentionResponse.AlreadySet
            if (
                currentTime - self.intentionGracePeriod
            ) > currentInterval.startTime:
                return IntentionResponse.TooLate
            if description:
                currentInterval.intention = Intention(description, None)
            return IntentionResponse.WasSet
        # unreachable, really
        return IntentionResponse.OnBreak

    def evaluateIntention(
        self, pomodoro: Pomodoro, success: IntentionSuccess
    ) -> None:
        """
        Evaluate the given pomodoro's intention as successful or not.
        """
        if (intention := pomodoro.intention) is None:
            print("intention is None, not setting")
            return
        print("set to", success)
        intention.wasSuccessful = success

    def achievedPomodoros(self) -> Sequence[Pomodoro]:
        return [
            each
            for each in self.elapsedIntervals
            if isinstance(each, Pomodoro)
            and each.intention is not None
            and each.intention.wasSuccessful == IntentionSuccess.Achieved
        ]

    def focusedPomodoros(self) -> Sequence[Pomodoro]:
        return [
            each
            for each in self.elapsedIntervals
            if isinstance(each, Pomodoro)
            and each.intention is not None
            and each.intention.wasSuccessful == IntentionSuccess.Focused
        ]

    def successfulPomodoros(self) -> Sequence[Pomodoro]:
        return [
            each
            for each in self.elapsedIntervals
            if isinstance(each, Pomodoro)
            and each.intention is not None
            and each.intention.wasSuccessful
            not in (False, IntentionSuccess.Distracted)
        ]

    def failedPomodoros(self) -> Sequence[Pomodoro]:
        allFailed = [
            each
            for (idx, each) in enumerate(self.elapsedIntervals)
            if isinstance(each, Pomodoro)
            and (
                each.intention is None
                or each.intention.wasSuccessful
                in (False, IntentionSuccess.Distracted)
            )
        ]
        if self.currentIsFailed():
            current = self.pendingIntervals[0]
            assert isinstance(current, Pomodoro)
            allFailed.insert(0, current)
        return allFailed

    def unEvaluatedPomodoros(self) -> Sequence[Pomodoro]:
        """
        List of pomodoros that haven't yet been evaluated and the user needs to
        confirm or reject their success.
        """
        unEvaluated = [
            each
            for each in self.elapsedIntervals
            if isinstance(each, Pomodoro)
            and each.intention is not None
            and each.intention.wasSuccessful is None
        ]
        # we can have at most 2 unevaluated poms. if we're on break 2 can be in
        # elapsedIntervals; if we're active then only 1 can be.
        offset = -1
        if not self.pendingIntervals or isinstance(
            self.pendingIntervals[0], Break
        ):
            offset = -2
        for failedAlready in unEvaluated[:offset]:
            assert failedAlready.intention is not None
            failedAlready.intention.wasSuccessful = (
                IntentionSuccess.NeverEvaluated
            )
        return unEvaluated[offset:]

    def currentIsFailed(self) -> bool:
        if not self.pendingIntervals:
            return False
        current = self.pendingIntervals[0]
        if not isinstance(current, Pomodoro):
            return False
        return current.intention is None and (
            self.lastUpdateTime
            > (current.startTime + self.intentionGracePeriod)
        )

    def pendingPomodoros(self) -> Sequence[Pomodoro]:
        """
        List of pomodoros that have yet to complete.
        """
        allPending = [
            each
            for each in self.pendingIntervals
            if isinstance(each, Pomodoro)
        ]
        if self.currentIsFailed():
            allPending.pop(0)
        return allPending

    def bonusPomodoro(self, currentTime: datetime) -> Pomodoro:
        """
        Create a new pomodoro at the end of the day.
        """

        def lengths():
            allIntervals = self.elapsedIntervals + self.pendingIntervals
            if allIntervals:
                startingPoint = allIntervals[-1].endTime
                iterIntervals = iter(allIntervals)
                firstPom = next(
                    each
                    for each in iterIntervals
                    if isinstance(each, Pomodoro)
                )
                firstBreak = next(
                    each for each in iterIntervals if isinstance(each, Break)
                )
                pomodoroLength = firstPom.endTime - firstPom.startTime
                breakLength = firstBreak.endTime - firstBreak.startTime
            else:
                # we need to save these attributes in the constructor so we
                # don't need to synthesize defaults here.
                startingPoint = self.endTime
                pomodoroLength = timedelta(minutes=25)
                breakLength = timedelta(minutes=5)
            return startingPoint, pomodoroLength, breakLength

        startingPoint, pomodoroLength, breakLength = lengths()
        newStartTime = max(startingPoint, currentTime)
        newPomodoro = Pomodoro(
            None, newStartTime, newStartTime + pomodoroLength
        )
        newBreak = Break(
            newPomodoro.endTime, newPomodoro.endTime + breakLength
        )
        self.pendingIntervals.append(newPomodoro)
        self.pendingIntervals.append(newBreak)
        print("created bonus", newPomodoro, newBreak)
        return newPomodoro

    def advanceToTime(
        self, currentTime: datetime, observer: PomObserver
    ) -> None:
        """
        Advance this Day to the given time, emitting observer notifications
        along the way.
        """
        if not self.pendingIntervals:
            # dayOver is emitted once, below.
            return
        while (
            self.pendingIntervals
            and currentTime > self.pendingIntervals[0].endTime
        ):
            # Notification: interval complete
            self.elapsedIntervals.append(
                elapsingInterval := self.pendingIntervals.pop(0)
            )
            if isinstance(elapsingInterval, Pomodoro):
                if elapsingInterval.intention is None:
                    observer.elapsedWithNoIntention(elapsingInterval)
        if not self.pendingIntervals:
            observer.dayOver()
            return
        currentInterval = self.pendingIntervals[0]
        # No elapsed intervals means we've never sent the 'starting'
        # notification, so do that now.
        if (self.lastUpdateTime <= currentInterval.startTime) and (
            currentTime > currentInterval.startTime
        ):
            if isinstance(currentInterval, Break):
                observer.breakStarting(currentInterval)
            elif isinstance(currentInterval, Pomodoro):
                observer.pomodoroStarting(self, currentInterval)

        totalTD = currentInterval.endTime - currentInterval.startTime
        elapsedTD = currentTime - currentInterval.startTime
        total = totalTD.total_seconds()
        elapsed = elapsedTD.total_seconds()
        rawPct = elapsed / total
        if 0.0 <= rawPct <= 1.0:
            # otherwise we're outside the bounds of the interval and we should
            # not report on it
            observer.progressUpdate(
                currentInterval, rawPct, self.expressIntention(currentTime, "")
            )
        self.lastUpdateTime = currentTime
