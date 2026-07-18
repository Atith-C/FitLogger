from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import ActivityLevel, BodyMeasurement, CalorieCalculation, Sex, UserProfile


class RegistrationForm(UserCreationForm):
    """Registration with a required, unique email.

    Password hashing and password-strength validation come from
    UserCreationForm — we never touch raw passwords ourselves.
    """

    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        # Django's User.email is not unique at the database level, so the
        # duplicate check has to be made here.
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class UserProfileForm(forms.ModelForm):
    """Fitness profile. These values feed the AI planner and the adherence
    calculation, so the field validators on the model matter."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Replace Django's default "---------" empty option with a real prompt.
        self.fields["sex"].choices = [("", "Choose your Gender"), *Sex.choices]

    class Meta:
        model = UserProfile
        # Field order here is the order the form renders in.
        fields = (
            "age",
            "sex",
            "weight_kg",
            "height_cm",
            "goal",
            "days_per_week",
            "experience_level",
            "workout_location",
            "session_duration",
        )
        widgets = {
            "age": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "min": UserProfile.MIN_AGE,
                    "max": UserProfile.MAX_AGE,
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            ),
            "sex": forms.Select(attrs={"class": "form-select form-select-lg"}),
            "weight_kg": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "min": UserProfile.MIN_WEIGHT_KG,
                    "max": UserProfile.MAX_WEIGHT_KG,
                    "step": "0.1",
                    "inputmode": "decimal",
                    "autocomplete": "off",
                }
            ),
            "height_cm": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "min": UserProfile.MIN_HEIGHT_CM,
                    "max": UserProfile.MAX_HEIGHT_CM,
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            ),
            "goal": forms.Select(attrs={"class": "form-select form-select-lg"}),
            "days_per_week": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "min": UserProfile.MIN_DAYS_PER_WEEK,
                    "max": UserProfile.MAX_DAYS_PER_WEEK,
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            ),
            "experience_level": forms.Select(attrs={"class": "form-select form-select-lg"}),
            "workout_location": forms.Select(attrs={"class": "form-select form-select-lg"}),
            "session_duration": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "min": UserProfile.MIN_SESSION_DURATION,
                    "max": UserProfile.MAX_SESSION_DURATION,
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            ),
        }
        labels = {
            "age": "Age",
            "sex": "Gender",
            "weight_kg": "Weight (kg)",
            "height_cm": "Height (cm)",
            "days_per_week": "Training days per week",
            "session_duration": "Typical session length (minutes)",
        }


class BodyMeasurementForm(forms.ModelForm):
    """Log one weigh-in. Only user is resolved server-side, never submitted."""

    class Meta:
        model = BodyMeasurement
        fields = ("recorded_on", "weight_kg", "body_fat_percentage", "muscle_mass_kg", "notes")
        widgets = {
            "recorded_on": forms.DateInput(
                attrs={"type": "date", "class": "form-control form-control-lg"}
            ),
            "weight_kg": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "step": "0.1",
                    "inputmode": "decimal",
                    "min": BodyMeasurement.MIN_WEIGHT_KG,
                    "max": BodyMeasurement.MAX_WEIGHT_KG,
                }
            ),
            "body_fat_percentage": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "step": "0.1",
                    "inputmode": "decimal",
                    "placeholder": "optional",
                }
            ),
            "muscle_mass_kg": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "step": "0.1",
                    "inputmode": "decimal",
                    "placeholder": "optional",
                }
            ),
            "notes": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "optional"}
            ),
        }
        labels = {
            "recorded_on": "Date",
            "weight_kg": "Weight (kg)",
            "body_fat_percentage": "Body fat (%)",
            "muscle_mass_kg": "Muscle mass (kg)",
        }


class CalorieCalculationForm(forms.ModelForm):
    """Inputs for the calorie calculator. Only the calculation is stored; the
    computed calories are worked out in the service, not submitted."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Gender is radio buttons — just Male/Female, no blank option.
        self.fields["sex"].choices = list(Sex.choices)
        # Activity is a dropdown — show a prompt instead of Django's "---------".
        self.fields["activity_level"].choices = [
            ("", "Choose activity level"),
            *ActivityLevel.choices,
        ]

    class Meta:
        model = CalorieCalculation
        fields = ("age", "sex", "height_cm", "weight_kg", "activity_level")
        widgets = {
            "age": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "min": CalorieCalculation.MIN_AGE,
                    "max": CalorieCalculation.MAX_AGE,
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            ),
            "sex": forms.RadioSelect(),
            "height_cm": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "min": CalorieCalculation.MIN_HEIGHT_CM,
                    "max": CalorieCalculation.MAX_HEIGHT_CM,
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            ),
            "weight_kg": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-lg",
                    "min": CalorieCalculation.MIN_WEIGHT_KG,
                    "max": CalorieCalculation.MAX_WEIGHT_KG,
                    "step": "0.1",
                    "inputmode": "decimal",
                    "autocomplete": "off",
                }
            ),
            "activity_level": forms.Select(attrs={"class": "form-select form-select-lg"}),
        }
        labels = {
            "age": "Age",
            "sex": "Gender",
            "height_cm": "Height (cm)",
            "weight_kg": "Weight (kg)",
            "activity_level": "Activity level",
        }
