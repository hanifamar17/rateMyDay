from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, DateField, IntegerField, TextAreaField, EmailField
from wtforms.validators import DataRequired, Email, EqualTo, Length

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember me")
    submit = SubmitField("Login")

class RegisterForm(FlaskForm):
    first_name = StringField("First Name*", validators=[DataRequired(), Length(min=2, max=50)])
    last_name = StringField("Last Name")
    email = EmailField("Email*", validators=[DataRequired(), Email()])
    password = PasswordField("Password*", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm Password*", 
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )
    submit = SubmitField("Create Account")

class RatingForm(FlaskForm):
    date = DateField("Date", validators=[DataRequired()])
    rating = IntegerField("Rating", validators=[DataRequired()])
    journal = TextAreaField("Journal")
    submit = SubmitField("Submit")