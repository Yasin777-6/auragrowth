from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction
import json
import requests

from .models import Profile, Quest, Habit, LogEntry, AIResponse, StatusEffect
from .utils import generate_ai_response, parse_ai_action, generate_daily_quests, clean_ai_response


def welcome(request):
    """Welcome/Landing page with anime intro"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'welcome.html')


def register(request):
    """Character creation/registration page"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        name = request.POST.get('name')
        role = request.POST.get('role', 'student')
        interests = request.POST.getlist('interests')
        goal = request.POST.get('goal', '')
        
        # Validate input
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists')
            return render(request, 'register.html')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists')
            return render(request, 'register.html')
        
        try:
            with transaction.atomic():
                # Create user
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=name
                )
                
                # Generate character class and starting stats with AI
                ai_prompt = f"""
                Analyze this new RPG player:
                Name: {name}
                Role: {role}
                Interests: {', '.join(interests)}
                Goal: {goal}
                
                Create a character profile with:
                1. A cool RPG class name (like "Scholar of Focus", "Warrior of Discipline")
                2. Starting stat bonuses (distribute 10 extra points among STR, INT, CHR, END, LCK)
                3. Brief welcome message in character
                
                Return JSON: {{"class": "class_name", "stats": {{"strength": 12, "intelligence": 15, ...}}, "message": "welcome_text"}}
                """
                
                ai_result = generate_ai_response(ai_prompt)
                try:
                    character_data = json.loads(ai_result)
                except:
                    # Fallback if AI fails
                    character_data = {
                        "class": "Novice Adventurer",
                        "stats": {"strength": 12, "intelligence": 12, "charisma": 11, "endurance": 11, "luck": 14},
                        "message": f"Welcome, {name}! Your journey begins now."
                    }
                
                # Create profile
                profile = Profile.objects.create(
                    user=user,
                    name=name,
                    character_class=character_data.get('class', 'Novice Adventurer'),
                    strength=character_data['stats'].get('strength', 10),
                    intelligence=character_data['stats'].get('intelligence', 10),
                    charisma=character_data['stats'].get('charisma', 10),
                    endurance=character_data['stats'].get('endurance', 10),
                    luck=character_data['stats'].get('luck', 10),
                )
                
                # Create welcome AI message
                AIResponse.objects.create(
                    profile=profile,
                    role='assistant',
                    content=character_data.get('message', f'Welcome to Aura Growth, {name}!')
                )
                
                # Generate first daily quests
                generate_daily_quests(profile)
                
                # Log in the user
                login(request, user)
                messages.success(request, f'Character created! Welcome, {profile.character_class}!')
                return redirect('dashboard')
                
        except Exception as e:
            messages.error(request, f'Error creating character: {str(e)}')
            return render(request, 'register.html')
    
    return render(request, 'register.html')


@login_required
def dashboard(request):
    """Main RPG dashboard with stats, quests, and status"""
    profile = get_object_or_404(Profile, user=request.user)
    
    # Get active quests
    daily_quests = profile.quests.filter(
        quest_type='daily',
        completed=False,
        due_date__gte=timezone.now().date()
    )[:5]
    
    # Get active habits
    active_habits = profile.habits.filter(active=True)[:3]
    
    # Get active status effects
    active_effects = profile.status_effects.filter(
        active=True,
        expires_at__gt=timezone.now()
    )
    
    # Calculate XP progress
    xp_progress = (profile.total_xp / profile.xp_to_next_level) * 100
    
    context = {
        'profile': profile,
        'daily_quests': daily_quests,
        'active_habits': active_habits,
        'active_effects': active_effects,
        'xp_progress': xp_progress,
    }
    
    return render(request, 'dashboard.html', context)


@login_required
def quests(request):
    """Quest log page showing all quests"""
    profile = get_object_or_404(Profile, user=request.user)
    
    # Get quests by type
    daily_quests = profile.quests.filter(quest_type='daily').order_by('-created_at')
    habit_quests = profile.quests.filter(quest_type='habit').order_by('-created_at')
    challenge_quests = profile.quests.filter(quest_type='challenge').order_by('-created_at')
    bonus_quests = profile.quests.filter(quest_type='bonus').order_by('-created_at')
    
    context = {
        'profile': profile,
        'daily_quests': daily_quests,
        'habit_quests': habit_quests,
        'challenge_quests': challenge_quests,
        'bonus_quests': bonus_quests,
    }
    
    return render(request, 'quests.html', context)


@login_required
def stats(request):
    """Stats and progress page"""
    profile = get_object_or_404(Profile, user=request.user)
    
    # Get recent log entries for progress tracking
    recent_logs = profile.log_entries.all()[:20]
    
    # Calculate completion rates
    total_quests = profile.quests.count()
    completed_quests = profile.quests.filter(completed=True).count()
    completion_rate = (completed_quests / total_quests * 100) if total_quests > 0 else 0
    
    context = {
        'profile': profile,
        'recent_logs': recent_logs,
        'completion_rate': completion_rate,
        'total_quests': total_quests,
        'completed_quests': completed_quests,
    }
    
    return render(request, 'stats.html', context)


@login_required
def chat(request):
    """AI chat interface"""
    profile = get_object_or_404(Profile, user=request.user)
    
    if request.method == 'POST':
        user_message = request.POST.get('message', '').strip()
        if not user_message:
            return JsonResponse({'error': 'Empty message'}, status=400)
        
        try:
            # Don't save user message - ephemeral chat
            
            # Generate AI response with action parsing
            ai_prompt = f"""
            You are an RPG mentor for {profile.name}, a Level {profile.level} {profile.character_class}.
            Current stats: STR:{profile.strength} INT:{profile.intelligence} CHR:{profile.charisma} END:{profile.endurance} LCK:{profile.luck}
            
            User said: "{user_message}"
            
            Parse for actions like:
            - Quest completion ("I finished my workout", "completed reading")
            - New habit requests ("I want to start meditating daily")
            - Progress updates ("I'm feeling motivated", "struggled today")
            
            Respond in character as a {profile.ai_personality} mentor.
            Keep your response conversational and engaging, without JSON code blocks.
            """
            
            raw_ai_response = generate_ai_response(ai_prompt)
            
            # Parse actions BEFORE cleaning the response
            action_data = parse_ai_action(raw_ai_response, profile)
            
            # Clean the response for display
            clean_response = clean_ai_response(raw_ai_response)
            
            # Don't save AI response - ephemeral chat
            
            return JsonResponse({
                'response': clean_response,
                'action_data': action_data,
                'timestamp': timezone.now().isoformat()
            })
            
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    # No chat history - ephemeral chat
    context = {
        'profile': profile,
    }
    
    return render(request, 'chat.html', context)


@login_required
def settings(request):
    """User settings and customization"""
    profile = get_object_or_404(Profile, user=request.user)
    
    if request.method == 'POST':
        # Update profile settings
        profile.name = request.POST.get('name', profile.name)
        profile.avatar = request.POST.get('avatar', profile.avatar)
        profile.ai_personality = request.POST.get('ai_personality', profile.ai_personality)
        profile.timezone = request.POST.get('timezone', profile.timezone)
        profile.save()
        
        messages.success(request, 'Settings updated successfully!')
        return redirect('settings')
    
    context = {
        'profile': profile,
    }
    
    return render(request, 'settings.html', context)


# HTMX API endpoints
@login_required
@require_http_methods(["POST"])
def complete_quest(request, quest_id):
    """HTMX endpoint to complete a quest"""
    try:
        profile = get_object_or_404(Profile, user=request.user)
        quest = get_object_or_404(Quest, id=quest_id, profile=profile)
        
        # Check if quest is already completed
        if quest.completed:
            return JsonResponse({
                'success': False, 
                'message': 'Quest already completed',
                'already_completed': True
            })
        
        # Check if quest is still valid (for daily quests)
        if quest.quest_type == 'daily' and quest.due_date and quest.due_date.date() < timezone.now().date():
            return JsonResponse({
                'success': False,
                'message': 'Quest has expired',
                'expired': True
            })
        
        # Complete the quest
        if quest.complete_quest():
            # Create log entry
            LogEntry.objects.create(
                profile=profile,
                action_type='quest_completed',
                action_description=f'Completed quest: {quest.title}',
                xp_gained=quest.reward_xp
            )
            
            # Refresh profile to get updated level
            profile.refresh_from_db()
            
            return JsonResponse({
                'success': True,
                'xp_gained': quest.reward_xp,
                'stat_gains': {
                    'strength': quest.reward_strength or 0,
                    'intelligence': quest.reward_intelligence or 0,
                    'charisma': quest.reward_charisma or 0,
                    'endurance': quest.reward_endurance or 0,
                    'luck': quest.reward_luck or 0,
                },
                'new_level': profile.level,
                'message': f'Quest completed! +{quest.reward_xp} XP',
                'quest_title': quest.title
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Failed to complete quest. Please try again.'
            })
            
    except Quest.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Quest not found'
        }, status=404)
    except Exception as e:
        import traceback
        print(f"Quest completion error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'message': f'An error occurred while completing the quest: {str(e)}'
        }, status=500)


@login_required
def refresh_stats(request):
    """HTMX endpoint to refresh stats display"""
    profile = get_object_or_404(Profile, user=request.user)
    
    xp_progress = (profile.total_xp / profile.xp_to_next_level) * 100
    
    return JsonResponse({
        'level': profile.level,
        'total_xp': profile.total_xp,
        'xp_to_next_level': profile.xp_to_next_level,
        'xp_progress': xp_progress,
        'strength': profile.strength,
        'intelligence': profile.intelligence,
        'charisma': profile.charisma,
        'endurance': profile.endurance,
        'luck': profile.luck,
    })


@login_required
@require_http_methods(["POST"])
def generate_new_quests(request):
    """Generate new daily quests"""
    profile = get_object_or_404(Profile, user=request.user)
    
    try:
        new_quests = generate_daily_quests(profile)
        return JsonResponse({
            'success': True,
            'message': f'Generated {len(new_quests)} new quests!',
            'quest_count': len(new_quests)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error generating quests: {str(e)}'
        })
