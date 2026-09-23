/*
 * FatBoss cosmetics for the legacy mod cgame.
 *
 * Client side only. This cgame ships in a zzz_fatboss_*.pk3 next to the
 * official legacy_v*.pk3, so the server keeps running the official qagame.
 * Nothing here may change playerState, prediction or input: it only moves
 * the first-person viewmodel.
 */

#include "cg_local.h"

#define FATBOSS_CGAME_VERSION "poc-1"

#define FB_INSPECT_IN_TIME   350
#define FB_INSPECT_HOLD_TIME 3000
#define FB_INSPECT_OUT_TIME  350

/**
 * Inspect pose per weapon. Angles (pitch, yaw, roll) rotate the viewmodel
 * around tag_weapon; offset (forward, right, up) moves it along the view axis.
 */
typedef struct
{
	int weapon;
	float angles[3];
	float offset[3];
} fbInspectPose_t;

static const fbInspectPose_t fbInspectPoses[] =
{
	{ WP_KNIFE,         { -6.0f, 70.0f, -20.0f }, { -2.0f, -14.0f, 8.0f  } },
	{ WP_KNIFE_KABAR,   { -6.0f, 70.0f, -20.0f }, { -2.0f, -14.0f, 8.0f  } },
	{ WP_LUGER,         { -4.0f, 75.0f, -8.0f  }, { -2.0f, -18.0f, 10.0f } },
	{ WP_COLT,          { -4.0f, 75.0f, -8.0f  }, { -2.0f, -18.0f, 10.0f } },
	{ WP_SILENCER,      { -4.0f, 75.0f, -8.0f  }, { -2.0f, -18.0f, 10.0f } },
	{ WP_SILENCED_COLT, { -4.0f, 75.0f, -8.0f  }, { -2.0f, -18.0f, 10.0f } },
	{ WP_MP40,          { -4.0f, 60.0f, -10.0f }, { -4.0f, -14.0f, 8.0f  } },
	{ WP_THOMPSON,      { -4.0f, 60.0f, -10.0f }, { -4.0f, -14.0f, 8.0f  } },
	{ WP_KAR98,         { -3.0f, 50.0f, -8.0f  }, { -6.0f, -12.0f, 6.0f  } },
	{ WP_CARBINE,       { -3.0f, 50.0f, -8.0f  }, { -6.0f, -12.0f, 6.0f  } },
	{ WP_GPG40,         { -3.0f, 50.0f, -8.0f  }, { -6.0f, -12.0f, 6.0f  } },
	{ WP_M7,            { -3.0f, 50.0f, -8.0f  }, { -6.0f, -12.0f, 6.0f  } },
};

static struct
{
	qboolean active;
	qboolean ending;
	int startTime;
	int endTime;
	int weapon;
	float endFraction;
	const fbInspectPose_t *pose;
} fbInspect;

static const fbInspectPose_t *CG_FatBoss_InspectPose(int weapon)
{
	int i;

	for (i = 0; i < (int)ARRAY_LEN(fbInspectPoses); i++)
	{
		if (fbInspectPoses[i].weapon == weapon)
		{
			return &fbInspectPoses[i];
		}
	}
	return NULL;
}

/**
 * @brief Only inspect an idle, supported weapon held by the local player.
 */
static qboolean CG_FatBoss_InspectAllowed(const playerState_t *ps)
{
	usercmd_t cmd;

	if (!cg.snap || cg.demoPlayback || cg.renderingThirdPerson
	    || cg.editingSpeakers || cg.testGun || cg.showGameView || cgs.dbShowing
	    || cg_drawGun.integer == 0 || ps->pm_type != PM_NORMAL
	    || ps->stats[STAT_HEALTH] <= 0
	    || ps->persistant[PERS_TEAM] == TEAM_SPECTATOR
	    || (ps->pm_flags & (PMF_FOLLOW | PMF_LIMBO))
	    || (ps->eFlags & (EF_FIRING | EF_MG42_ACTIVE | EF_AAGUN_ACTIVE | EF_MOUNTEDTANK | EF_PRONE_MOVING))
	    || ps->persistant[PERS_HWEAPON_USE]
	    || cg.zoomed || cg.zoomedBinoc || cg.zoomval != 0.0f
	    || cg.weapzoomActive
	    || ps->weaponstate != WEAPON_READY || cg.weaponSelect != ps->weapon
	    || !CG_FatBoss_InspectPose(ps->weapon))
	{
		return qfalse;
	}

	// cancel before prediction enters a firing or reload state, never consume input
	if (trap_GetUserCmd(trap_GetCurrentCmdNumber(), &cmd)
	    && ((cmd.buttons & BUTTON_ATTACK) || (cmd.wbuttons & (WBUTTON_RELOAD | WBUTTON_ATTACK2))))
	{
		return qfalse;
	}

	return qtrue;
}

static float CG_FatBoss_Ease(float fraction)
{
	if (fraction <= 0.0f)
	{
		return 0.0f;
	}
	if (fraction >= 1.0f)
	{
		return 1.0f;
	}
	return fraction * fraction * (3.0f - 2.0f * fraction);
}

/**
 * @brief The pose comes from time only, so it does not depend on render pass count.
 */
static float CG_FatBoss_InspectFraction(void)
{
	int elapsed;

	if (!fbInspect.active)
	{
		return 0.0f;
	}
	if (fbInspect.ending)
	{
		elapsed = cg.time - fbInspect.endTime;
		return fbInspect.endFraction * (1.0f - CG_FatBoss_Ease((float)elapsed / FB_INSPECT_OUT_TIME));
	}

	elapsed = cg.time - fbInspect.startTime;
	if (elapsed < FB_INSPECT_IN_TIME)
	{
		return CG_FatBoss_Ease((float)elapsed / FB_INSPECT_IN_TIME);
	}
	if (elapsed < FB_INSPECT_IN_TIME + FB_INSPECT_HOLD_TIME)
	{
		return 1.0f;
	}
	return 1.0f - CG_FatBoss_Ease((float)(elapsed - FB_INSPECT_IN_TIME - FB_INSPECT_HOLD_TIME) / FB_INSPECT_OUT_TIME);
}

/**
 * @brief +ilookatweapon: start the inspect, or ease back on a second press.
 */
void CG_FatBoss_Inspect_f(void)
{
	if (fbInspect.active)
	{
		if (!fbInspect.ending)
		{
			fbInspect.endFraction = CG_FatBoss_InspectFraction();
			fbInspect.endTime     = cg.time;
			fbInspect.ending      = qtrue;
		}
		return;
	}
	if (!CG_FatBoss_InspectAllowed(&cg.predictedPlayerState))
	{
		return;
	}

	fbInspect.active    = qtrue;
	fbInspect.ending    = qfalse;
	fbInspect.startTime = cg.time;
	fbInspect.weapon    = cg.predictedPlayerState.weapon;
	fbInspect.pose      = CG_FatBoss_InspectPose(fbInspect.weapon);
}

/**
 * @brief -ilookatweapon: registered so the key release is not sent to the server.
 */
void CG_FatBoss_InspectUp_f(void)
{
}

void CG_FatBoss_CancelInspect(void)
{
	fbInspect.active = qfalse;
	fbInspect.ending = qfalse;
}

/**
 * @brief Gameplay actions end the inspect at once; a finished one eases out.
 */
void CG_FatBoss_UpdateInspect(const playerState_t *ps)
{
	if (!fbInspect.active)
	{
		return;
	}
	if (!CG_FatBoss_InspectAllowed(ps) || ps->weapon != fbInspect.weapon
	    || cg.time < fbInspect.startTime
	    || (fbInspect.ending && cg.time - fbInspect.endTime >= FB_INSPECT_OUT_TIME)
	    || (!fbInspect.ending && cg.time - fbInspect.startTime >= FB_INSPECT_IN_TIME + FB_INSPECT_HOLD_TIME + FB_INSPECT_OUT_TIME))
	{
		CG_FatBoss_CancelInspect();
	}
}

/**
 * @brief Rotate the viewmodel around its weapon tag; camera and aim stay unchanged.
 */
void CG_FatBoss_ApplyInspect(refEntity_t *hand)
{
	float         fraction = CG_FatBoss_InspectFraction();
	vec3_t        angles, inspectAxis[3], rotatedAxis[3], pivot;
	orientation_t tag;
	int           i;

	if (fraction <= 0.0f || !fbInspect.pose || trap_R_LerpTag(&tag, hand, "tag_weapon", 0) < 0)
	{
		return;
	}

	VectorScale(fbInspect.pose->angles, fraction, angles);
	AnglesToAxis(angles, inspectAxis);
	MatrixMultiply(inspectAxis, hand->axis, rotatedAxis);

	VectorCopy(hand->origin, pivot);
	for (i = 0; i < 3; i++)
	{
		VectorMA(pivot, tag.origin[i], hand->axis[i], pivot);
	}
	AxisCopy(rotatedAxis, hand->axis);
	VectorCopy(pivot, hand->origin);
	for (i = 0; i < 3; i++)
	{
		VectorMA(hand->origin, -tag.origin[i], hand->axis[i], hand->origin);
	}

	for (i = 0; i < 3; i++)
	{
		VectorMA(hand->origin, fbInspect.pose->offset[i] * fraction, cg.refdef_current->viewaxis[i], hand->origin);
	}
}

void CG_FatBoss_Version_f(void)
{
	CG_Printf("FatBoss cgame %s on %s %s\n", FATBOSS_CGAME_VERSION, MODNAME, ETLEGACY_VERSION);
}

void CG_FatBoss_Init(void)
{
	Com_Memset(&fbInspect, 0, sizeof(fbInspect));
	Com_Printf(S_COLOR_YELLOW "FatBoss cgame %s loaded\n", FATBOSS_CGAME_VERSION);
}
