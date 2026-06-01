from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q
from .models import UserEmail, UserPhone

class MultiAuthBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        # In Django, 'username' is whatever the user typed into the login box.
        # It could be an actual username, an email, or a phone number.
        
        user = None
        
        try:
            # 1. First, check if they typed their standard username or primary email
            user = User.objects.get(Q(username=username) | Q(email=username))
            
        except User.DoesNotExist:
            # 2. If not found, check our new UserEmail table
            try:
                user_email = UserEmail.objects.get(email=username)
                user = user_email.user
                
            except UserEmail.DoesNotExist:
                # 3. If STILL not found, check our new UserPhone table
                try:
                    user_phone = UserPhone.objects.get(phone_number=username)
                    user = user_phone.user
                    
                except UserPhone.DoesNotExist:
                    # They don't exist anywhere in the system
                    return None

        # 4. If we found a user in ANY of those tables, check if the password is correct
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
            
        return None