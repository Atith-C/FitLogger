from django import forms

from .models import Exercise, MuscleGroup, WorkoutSession, WorkoutSet


class ExerciseForm(forms.ModelForm):
    """Add or edit a library exercise (admin only). The unique-name check comes
    from the model, so a duplicate is rejected with a clear field error."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # muscle_group has no model default, so Django would prepend a blank
        # "---------" option. Drop it — only real muscle groups belong here.
        self.fields["muscle_group"].choices = MuscleGroup.choices

    class Meta:
        model = Exercise
        fields = ("name", "muscle_group", "equipment")
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Incline Bench Press",
                    "autocomplete": "off",
                }
            ),
            "muscle_group": forms.Select(attrs={"class": "form-select"}),
            "equipment": forms.Select(attrs={"class": "form-select"}),
        }


class StartWorkoutForm(forms.ModelForm):
    """Name a new workout session."""

    class Meta:
        model = WorkoutSession
        fields = ("name",)
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "placeholder": "e.g. Push Day",
                    "autocomplete": "off",
                }
            )
        }
        labels = {"name": "Workout name"}


class WorkoutSetForm(forms.Form):
    """One logged set.

    A plain Form, not a ModelForm: session and exercise are resolved from
    request.user in the service layer, never taken from the submitted data.
    """

    weight = forms.DecimalField(
        min_value=0,
        max_digits=6,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-lg text-center",
                "inputmode": "decimal",  # numeric keypad on phones
                "step": "0.5",
                "min": "0",
                "placeholder": "kg",
            }
        ),
    )
    reps = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control form-control-lg text-center",
                "inputmode": "numeric",
                "min": "1",
                "placeholder": "reps",
            }
        ),
    )
