#include "LH3DSky.h"

#include <stdlib.h>
#include <time.h>
#include <string.h>
#include <math.h>

#include <re_common.h>

#include "LH3DMath.h"
#include "LH3DSubMesh.h"
#include "LH3DRender.h"
#include "LH3DAtmos.h"
#include "LH3DColor.h"
#include "LH3DMaterial.h"
#include "LH3DMesh.h"
#include "LH3DObject.h"
#include "LH3DTech.h"
#include "LH3DTexture.h"
#include "LHMatrix.h"
#include "LHPoint.h"

#define LH3D_SKY_MOON_ATMOS_BUFFER    0
#define LH3D_SKY_RGB444_CHANNEL_BITS  4
#define LH3D_SKY_RGB444_CHANNEL_MASK  0xf
#define LH3D_SKY_COLOUR_BLEND_SHIFT   8
#define LH3D_SKY_COLOUR_BLEND_SCALE   (1 << LH3D_SKY_COLOUR_BLEND_SHIFT)
#define LH3D_SKY_MOON_UPDATE_INTERVAL 2000
#define LH3D_SKY_MOON_SECONDS_PER_DAY 86400
#define LH3D_SKY_MOON_REFERENCE_DAY   10962
#define LH3D_SKY_MOON_CYCLE_DAYS      29.5305992
#define LH3D_SKY_MOON_UV_DIVISOR      400.0f
#define LH3D_SKY_MOON_UV_OFFSET       0.25f
#define LH3D_SKY_MOON_TILT_ANGLE      (-0.1308997f)
#define LH3D_SKY_MOON_SHADING_SCALE   0.65f
#define LH3D_SKY_SUNRISE_TIME         6.0f
#define LH3D_SKY_SUNSET_TIME          18.0f
#define LH3D_SKY_SUN_FADE_DURATION    3.0f
#define LH3D_SKY_SUN_FADE_START       (LH3D_SKY_SUNRISE_TIME - LH3D_SKY_SUN_FADE_DURATION)
#define LH3D_SKY_SUN_FADE_END         (LH3D_SKY_SUNSET_TIME + LH3D_SKY_SUN_FADE_DURATION)
#define LH3D_SKY_SUN_FADE_SCALE       (LH3D_SKY_ALPHA_MAX / LH3D_SKY_SUN_FADE_DURATION)
#define LH3D_SKY_SUN_ALTITUDE_MAX     7500.0f
#define LH3D_SKY_SUN_ALTITUDE_SCALE   (1.0f / (LH3D_SKY_HOURS_PER_HALF_DAY - LH3D_SKY_SUNRISE_TIME))
#define LH3D_SKY_PUBLIC_LIGHTS_DUSK   16.5f
#define LH3D_SKY_PUBLIC_LIGHTS_DAWN   7.0f
#define LH3D_SKY_PUBLIC_LIGHTS_FADE   1.0f

int         LH3DSky::g_b_we_are_inside_citadel;
float       LH3DSky::g_alpha_sun = LH3D_SKY_ALPHA_MAX;
float       LH3DSky::ONIGHT_FULL_TIME = 3.5f;
float       LH3DSky::ODUSK_START_TIME = 7.5f;
float       LH3DSky::ODUSK_END_TIME = 8.0f;
float       LH3DSky::ODAY_FULL_TIME = 8.5f;
float       LH3DSky::DAY_FULL_TIME;
float       LH3DSky::DUSK_END_TIME;
float       LH3DSky::DUSK_START_TIME;
float       LH3DSky::NIGHT_FULL_TIME;
int         LH3DSky::cury;
float       LH3DSky::newst;
float       LH3DSky::curst;
float       LH3DSky::curtime;
LH3DColor   LH3DSky::topcol;
LH3DColor   LH3DSky::lightcols[LH3D_SKY_LIGHT_COLOUR_COUNT];
void*       LH3DSky::bitmaps[SKY_TYPE_LAST][SKY_ALIGNMENT_LAST];
LHPoint     LH3DSky::g_sun_pos;
LH3DObject* LH3DSky::sunobj;
LH3DMesh*   LH3DSky::sun;
float       LH3DSky::moonphase;
LH3DObject* LH3DSky::moonobj;
LH3DMesh*   LH3DSky::moon;
LH3DObject* LH3DSky::sky;
LH3DMesh*   LH3DSky::skymesh;
float       LH3DSky::moonsize;
float       LH3DSky::overcast;
float       LH3DSky::evil;
bool32_t    LH3DSky::LightningGlow;

int   fog_fade;
float fog_blue;
float fog_green;
float fog_red;

LH3DTexture*  sky_texture[SKY_TYPE_LAST];
LH3DMaterial* sky_material[SKY_TYPE_LAST];

bool32_t g_jc_caca_first_init_sky = true;
int      g_fade;
bool     moonflip;

LH3DColor LH3DSky::Interpolate444Colour(uint16_t from, uint16_t to, int amount)
{
	LH3DColor result;
	if (amount <= 0)
	{
		int red = (from >> (LH3D_SKY_RGB444_CHANNEL_BITS * 2)) & LH3D_SKY_RGB444_CHANNEL_MASK;
		int green = (from >> LH3D_SKY_RGB444_CHANNEL_BITS) & LH3D_SKY_RGB444_CHANNEL_MASK;
		int blue = from & LH3D_SKY_RGB444_CHANNEL_MASK;
		int rgb = (((red << LH3D_COLOR_GREEN_SHIFT) + green) << LH3D_COLOR_GREEN_SHIFT) + blue;
		result = LH3DColor(rgb << LH3D_SKY_RGB444_CHANNEL_BITS);
	}
	else if (amount >= LH3D_SKY_COLOUR_BLEND_SCALE)
	{
		int red = (to >> (LH3D_SKY_RGB444_CHANNEL_BITS * 2)) & LH3D_SKY_RGB444_CHANNEL_MASK;
		int green = (to >> LH3D_SKY_RGB444_CHANNEL_BITS) & LH3D_SKY_RGB444_CHANNEL_MASK;
		int blue = to & LH3D_SKY_RGB444_CHANNEL_MASK;
		int rgb = (((red << LH3D_COLOR_GREEN_SHIFT) + green) << LH3D_COLOR_GREEN_SHIFT) + blue;
		result = LH3DColor(rgb << LH3D_SKY_RGB444_CHANNEL_BITS);
	}
	else
	{
		int red = (from >> (LH3D_SKY_RGB444_CHANNEL_BITS * 2)) & LH3D_SKY_RGB444_CHANNEL_MASK;
		int green = (from >> LH3D_SKY_RGB444_CHANNEL_BITS) & LH3D_SKY_RGB444_CHANNEL_MASK;
		int blue = from & LH3D_SKY_RGB444_CHANNEL_MASK;
		red = ((((to >> (LH3D_SKY_RGB444_CHANNEL_BITS * 2)) & LH3D_SKY_RGB444_CHANNEL_MASK) - red) * amount +
		       (red << LH3D_SKY_COLOUR_BLEND_SHIFT)) >>
		      LH3D_SKY_RGB444_CHANNEL_BITS;
		green = ((((to >> LH3D_SKY_RGB444_CHANNEL_BITS) & LH3D_SKY_RGB444_CHANNEL_MASK) - green) * amount +
		         (green << LH3D_SKY_COLOUR_BLEND_SHIFT)) >>
		        LH3D_SKY_RGB444_CHANNEL_BITS;
		blue = (((to & LH3D_SKY_RGB444_CHANNEL_MASK) - blue) * amount + (blue << LH3D_SKY_COLOUR_BLEND_SHIFT)) >>
		       LH3D_SKY_RGB444_CHANNEL_BITS;
		result.r = red;
		result.g = green;
		result.b = blue;
	}
	result.a = LH3D_COLOR_OPAQUE;
	return result;
}

void LH3DSky::SetDayNightTimes(float night, float dusk_start, float dusk_end, float day)
{
	NIGHT_FULL_TIME = night;
	DUSK_START_TIME = dusk_start;
	DUSK_END_TIME = dusk_end;
	DAY_FULL_TIME = day;
}

float LH3DSky::ConvertTime(float time, float from_night, float from_dusk_start, float from_dusk_end, float from_day,
                           float to_night, float to_dusk_start, float to_dusk_end, float to_day)
{
	bool isAfternoon = false;
	if (time > LH3D_SKY_HOURS_PER_HALF_DAY)
	{
		time = LH3D_SKY_HOURS_PER_DAY - time;
		isAfternoon = true;
	}

	SKY_TIME_INTERVAL interval;
	float             fraction;
	if (time < from_night)
	{
		interval = SKY_TIME_INTERVAL_NIGHT;
		fraction = time / from_night;
	}
	else if (time < from_dusk_start)
	{
		interval = SKY_TIME_INTERVAL_NIGHT_TO_DUSK;
		fraction = (time - from_night) / (from_dusk_start - from_night);
	}
	else if (time < from_dusk_end)
	{
		interval = SKY_TIME_INTERVAL_DUSK;
		fraction = (time - from_dusk_start) / (from_dusk_end - from_dusk_start);
	}
	else if (time < from_day)
	{
		interval = SKY_TIME_INTERVAL_DUSK_TO_DAY;
		fraction = (time - from_dusk_end) / (from_day - from_dusk_end);
	}
	else
	{
		interval = SKY_TIME_INTERVAL_DAY;
		fraction = (time - from_day) / (LH3D_SKY_HOURS_PER_HALF_DAY - from_day);
	}

	switch (interval)
	{
	case SKY_TIME_INTERVAL_NIGHT:
		time = fraction * to_night;
		break;
	case SKY_TIME_INTERVAL_NIGHT_TO_DUSK:
		time = to_night + fraction * (to_dusk_start - to_night);
		break;
	case SKY_TIME_INTERVAL_DUSK:
		time = to_dusk_start + fraction * (to_dusk_end - to_dusk_start);
		break;
	case SKY_TIME_INTERVAL_DUSK_TO_DAY:
		time = to_dusk_end + fraction * (to_day - to_dusk_end);
		break;
	case SKY_TIME_INTERVAL_DAY:
		time = to_day + fraction * (LH3D_SKY_HOURS_PER_HALF_DAY - to_day);
		break;
	}

	if (isAfternoon)
	{
		time = LH3D_SKY_HOURS_PER_DAY - time;
	}
	return time;
}

float LH3DSky::OldSkoolTime2Time(float time)
{
	return ConvertTime(time, ONIGHT_FULL_TIME, ODUSK_START_TIME, ODUSK_END_TIME, ODAY_FULL_TIME, NIGHT_FULL_TIME,
	                   DUSK_START_TIME, DUSK_END_TIME, DAY_FULL_TIME);
}

float LH3DSky::Time2OldSkoolTime(float time)
{
	return ConvertTime(time, NIGHT_FULL_TIME, DUSK_START_TIME, DUSK_END_TIME, DAY_FULL_TIME, ONIGHT_FULL_TIME,
	                   ODUSK_START_TIME, ODUSK_END_TIME, ODAY_FULL_TIME);
}

float LH3DSky::Time2SkyType(float time)
{
	float skyType = SKY_TYPE_DAY;
	if (time > LH3D_SKY_HOURS_PER_HALF_DAY)
	{
		time = LH3D_SKY_HOURS_PER_DAY - time;
	}
	if (time < NIGHT_FULL_TIME)
	{
		skyType = SKY_TYPE_NIGHT;
	}
	else if (time < DUSK_START_TIME)
	{
		skyType = SKY_TYPE_NIGHT - (time - NIGHT_FULL_TIME) / (DUSK_START_TIME - NIGHT_FULL_TIME);
	}
	else if (time < DUSK_END_TIME)
	{
		skyType = SKY_TYPE_DUSK;
	}
	else if (time < DAY_FULL_TIME)
	{
		skyType = SKY_TYPE_DUSK - (time - DUSK_END_TIME) / (DAY_FULL_TIME - DUSK_END_TIME);
	}
	return skyType;
}

void LH3DSky::ForceTime(float time)
{
	SetTime(time);
	curst = newst;
	cury = 0;
	CalculateTextures(newst, 0, LH3DTexture::g_b_use_low_res ? SKY_TEXTURE_HEIGHT_LOW : SKY_TEXTURE_HEIGHT);
	CalculateColours();
}

void LH3DSky::SetTime(float time)
{
	while (time < 0.0f)
	{
		time += LH3D_SKY_HOURS_PER_DAY;
	}
	while (time >= LH3D_SKY_HOURS_PER_DAY)
	{
		time -= LH3D_SKY_HOURS_PER_DAY;
	}
	curtime = time;
	newst = Time2SkyType(time);
}

void LH3DSky::Update()
{
	CalculateColours();
	int textureHeight = LH3DTexture::g_b_use_low_res ? SKY_TEXTURE_HEIGHT_LOW : SKY_TEXTURE_HEIGHT;
	if (cury >= textureHeight)
	{
		if (fabs(newst - curst) > SKY_TYPE_CHANGE_THRESHOLD)
		{
			curst = newst;
			cury = 0;
		}
		if (cury >= textureHeight)
		{
			return;
		}
	}
	CalculateTextures(curst, cury, SKY_TEXTURE_UPDATE_LINES);
	cury += SKY_TEXTURE_UPDATE_LINES;
}

void LH3DSky::Close()
{
	g_jc_caca_first_init_sky = true;
	for (int index = 0; index < SKY_TYPE_LAST; ++index)
	{
		if (sky_material[index] != NULL)
		{
			sky_material[index]->texture = NULL;
		}
		if (sky_texture[index] != NULL)
		{
			sky_texture[index]->Release();
		}
		for (int skyType = 0; skyType < SKY_TYPE_LAST; ++skyType)
		{
			if (bitmaps[skyType][SKY_ALIGNMENT_GOOD] == bitmaps[skyType][SKY_ALIGNMENT_NEUTRAL])
			{
				bitmaps[skyType][SKY_ALIGNMENT_GOOD] = NULL;
			}
			if (bitmaps[skyType][SKY_ALIGNMENT_EVIL] == bitmaps[skyType][SKY_ALIGNMENT_NEUTRAL])
			{
				bitmaps[skyType][SKY_ALIGNMENT_EVIL] = NULL;
			}
			if (bitmaps[skyType][index] != NULL)
			{
				free(bitmaps[skyType][index]);
			}
		}
	}
}

float LH3DSky::CalcMoonRot(bool32_t& changed)
{
	static time_t lastTime = 0;
	static int    lastTick = 0;
	int           tick = GetTickCount();
	if (tick - lastTick > LH3D_SKY_MOON_UPDATE_INTERVAL)
	{
		lastTime = 0;
		lastTick = tick;
	}
	if (lastTime == 0)
	{
		time(&lastTime);
		changed = true;
	}
	else
	{
		changed = false;
	}
	double cycle = (lastTime / LH3D_SKY_MOON_SECONDS_PER_DAY - LH3D_SKY_MOON_REFERENCE_DAY) / LH3D_SKY_MOON_CYCLE_DAYS;
	return (1.0 - (cycle - (int)cycle)) * TWO_PI;
}

void LH3DSky::CalcMoonPhase()
{
	LHMatrix rotation;
	rotation.SetRotationY(moonphase);
	LH3DSubMesh*    submesh = moon->submeshes[0];
	LH3DPrimitive** primitives = submesh->primitives_;
	int             count = submesh->NumPrimitives;
	for (int i = 0; i < count; ++i)
	{
		LH3DVertex* vertex = primitives[i]->Vertices;
		int         vertices = primitives[i]->NumVertices;
		while (vertices--)
		{
			LHPoint point = vertex->position;
			rotation.TransformPoint(point);
			vertex->uv.Set(point.x / LH3D_SKY_MOON_UV_DIVISOR + LH3D_SKY_MOON_UV_OFFSET,
			               point.y / LH3D_SKY_MOON_UV_DIVISOR + LH3D_SKY_MOON_UV_OFFSET);
			++vertex;
		}
	}
}

void LH3DSky::DrawMoonPost(LH3DColor& colour, LHMatrix& quad_matrix, LHMatrix& moon_matrix)
{
	enum MOON_VERTEX
	{
		MOON_VERTEX_LOWER_LEFT = 0,
		MOON_VERTEX_LOWER_RIGHT = 1,
		MOON_VERTEX_UPPER_LEFT = 2,
		MOON_VERTEX_UPPER_RIGHT = 3
	};

	LH3DAtmos::v_idx[LH3D_SKY_MOON_ATMOS_BUFFER][0] = MOON_VERTEX_LOWER_LEFT;
	LH3DAtmos::v_idx[LH3D_SKY_MOON_ATMOS_BUFFER][1] = MOON_VERTEX_LOWER_RIGHT;
	LH3DAtmos::v_idx[LH3D_SKY_MOON_ATMOS_BUFFER][2] = MOON_VERTEX_UPPER_RIGHT;
	LH3DAtmos::v_idx[LH3D_SKY_MOON_ATMOS_BUFFER][3] = MOON_VERTEX_UPPER_RIGHT;
	LH3DAtmos::v_idx[LH3D_SKY_MOON_ATMOS_BUFFER][4] = MOON_VERTEX_UPPER_LEFT;
	LH3DAtmos::v_idx[LH3D_SKY_MOON_ATMOS_BUFFER][5] = MOON_VERTEX_LOWER_LEFT;

	LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER][0] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER][1] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER][2] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER][3] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER][4] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER][5] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER][6] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER][7] = LH3D_SKY_MOON_UV_MAX;

	LH3DColor glowColour = colour;
	glowColour.r = (uint8_t)((int)glowColour.r / LH3D_SKY_MOON_RED_DIVISOR);
	glowColour.g = (uint8_t)((int)glowColour.g / LH3D_SKY_MOON_GREEN_DIVISOR);
	glowColour.b >>= LH3D_SKY_MOON_BLUE_SHIFT;

	LH3DAtmos::v_col[LH3D_SKY_MOON_ATMOS_BUFFER][MOON_VERTEX_LOWER_LEFT] = glowColour;
	LH3DAtmos::v_col[LH3D_SKY_MOON_ATMOS_BUFFER][MOON_VERTEX_LOWER_RIGHT] = glowColour;
	LH3DAtmos::v_col[LH3D_SKY_MOON_ATMOS_BUFFER][MOON_VERTEX_UPPER_LEFT] = glowColour;
	LH3DAtmos::v_col[LH3D_SKY_MOON_ATMOS_BUFFER][MOON_VERTEX_UPPER_RIGHT] = glowColour;

	LHPoint  lowerLeft(-LH3D_SKY_MOON_QUAD_SIZE, -LH3D_SKY_MOON_QUAD_SIZE, 0.0f);
	LHPoint& lowerLeftOutput = LH3DAtmos::v_pnt[LH3D_SKY_MOON_ATMOS_BUFFER][MOON_VERTEX_LOWER_LEFT];
	LHMATRIX_TRANSFORM_POINT(lowerLeftOutput, lowerLeft, quad_matrix);
	LHPoint  lowerRight(LH3D_SKY_MOON_QUAD_SIZE, -LH3D_SKY_MOON_QUAD_SIZE, 0.0f);
	LHPoint& lowerRightOutput = LH3DAtmos::v_pnt[LH3D_SKY_MOON_ATMOS_BUFFER][MOON_VERTEX_LOWER_RIGHT];
	LHMATRIX_TRANSFORM_POINT(lowerRightOutput, lowerRight, quad_matrix);
	LHPoint  upperLeft(-LH3D_SKY_MOON_QUAD_SIZE, LH3D_SKY_MOON_QUAD_SIZE, 0.0f);
	LHPoint& upperLeftOutput = LH3DAtmos::v_pnt[LH3D_SKY_MOON_ATMOS_BUFFER][MOON_VERTEX_UPPER_LEFT];
	LHMATRIX_TRANSFORM_POINT(upperLeftOutput, upperLeft, quad_matrix);
	LHPoint  upperRight(LH3D_SKY_MOON_QUAD_SIZE, LH3D_SKY_MOON_QUAD_SIZE, 0.0f);
	LHPoint& upperRightOutput = LH3DAtmos::v_pnt[LH3D_SKY_MOON_ATMOS_BUFFER][MOON_VERTEX_UPPER_RIGHT];
	LHMATRIX_TRANSFORM_POINT(upperRightOutput, upperRight, quad_matrix);

	LH3DTech::Draw3DWorldTriangle(LH3D_SKY_MOON_VERTEX_COUNT, LH3DAtmos::v_pnt[LH3D_SKY_MOON_ATMOS_BUFFER],
	                              LH3DAtmos::v_col[LH3D_SKY_MOON_ATMOS_BUFFER],
	                              LH3DAtmos::v_uv[LH3D_SKY_MOON_ATMOS_BUFFER], LH3D_SKY_MOON_TRIANGLE_COUNT,
	                              LH3DAtmos::v_idx[LH3D_SKY_MOON_ATMOS_BUFFER], LH3DAtmos::AdditiveMaterial, false);

	moonobj->matrix.Set(moon_matrix);
	moonobj->SetColorSpecular(colour.GetColor(), 0);
	moonobj->SetDrawWithGlobalAlpha(true);
	if (!moonflip)
	{
		moonobj->Draw();
		moonobj->SetColorSpecular(colour.GetColor(), 0);
		moonobj->SetDrawWithGlobalAlpha(true);
		moonobj->DrawUnderWater();
	}
}

void LH3DSky::CalcMoonMat(LHPoint& pos, LHMatrix& matrix, LHMatrix& moon_matrix)
{
	LHPoint cameraPos = LH3DTech::g_world_to_camera * pos;
	LHPoint forward;
	forward = cameraPos;
	forward.Normalise();
	LHPoint right;
	LHPoint up(0.0f, 1.0f, 0.0f);
	right.CrossProduct(up, forward);
	right.Normalise();
	up.CrossProduct(forward, right);
	matrix._11 = right.x;
	matrix._12 = right.y;
	matrix._13 = right.z;
	matrix._21 = up.x;
	matrix._22 = up.y;
	matrix._23 = up.z;
	matrix._31 = forward.x;
	matrix._32 = forward.y;
	matrix._33 = forward.z;
	matrix._41 = cameraPos.x;
	matrix._42 = cameraPos.y;
	matrix._43 = cameraPos.z;
	LHMatrix inverse;
	inverse.SetInverse(LH3DTech::g_world_to_camera);
	matrix.PostMultiply(inverse);
	matrix.ScaleMatrixOnly(moonsize);
	moon_matrix.Set(matrix);
	bool32_t changed = true;
	moonphase = CalcMoonRot(changed);
	if (changed)
	{
		CalcMoonPhase();
	}
	moon_matrix.RotateZ((moonflip ? -1 : 1) * LH3D_SKY_MOON_TILT_ANGLE);
	moon_matrix.RotateY(moonphase + PI_F);
	moon_matrix.ScaleMatrixOnly(LH3D_SKY_MOON_SHADING_SCALE);
}

void LH3DSky::DrawSky(int index, int alpha, int colour, int specular)
{
	sky->SetColorSpecular((colour & LH3D_COLOR_RGB_MASK) + (alpha << LH3D_COLOR_ALPHA_SHIFT), specular);
	LH3DSubMesh*    submesh = skymesh->submeshes[0];
	int             count = submesh->NumPrimitives;
	LH3DPrimitive** primitives = submesh->primitives_;
	for (int i = 0; i < count; ++i)
	{
		memcpy(&primitives[i]->Material, sky_material[index], sizeof(LH3DMaterial));
	}
	sky->SetNeedClipping(true);
	if (alpha != LH3D_SKY_ALPHA_MAX)
	{
		sky->SetDrawWithGlobalAlpha(true);
		if (g_b_any_voodoo)
		{
			LH3DRender::SetRenderState(D3DRENDERSTATE_TEXTUREPERSPECTIVE, false);
		}
		sky->Draw();
		LH3DRender::SetRenderState(D3DRENDERSTATE_TEXTUREPERSPECTIVE, true);
	}
	else
	{
		sky->SetDrawWithGlobalAlpha(false);
		if (g_b_any_voodoo)
		{
			LH3DRender::SetRenderState(D3DRENDERSTATE_TEXTUREPERSPECTIVE, false);
		}
		sky->Draw();
		LH3DRender::SetRenderState(D3DRENDERSTATE_TEXTUREPERSPECTIVE, true);
	}
}

float LH3DSky::GetSunAltitude()
{
	float time = Time2OldSkoolTime(curtime);
	float foldedTime = time;
	if (foldedTime > LH3D_SKY_SUNSET_TIME)
	{
		foldedTime = LH3D_SKY_SUNSET_TIME;
	}
	else if (foldedTime < LH3D_SKY_SUNRISE_TIME)
	{
		foldedTime = LH3D_SKY_SUNRISE_TIME;
	}
	if (foldedTime > LH3D_SKY_HOURS_PER_HALF_DAY)
	{
		foldedTime = LH3D_SKY_HOURS_PER_HALF_DAY - (foldedTime - LH3D_SKY_HOURS_PER_HALF_DAY);
	}
	float altitude = (foldedTime - LH3D_SKY_SUNRISE_TIME) * LH3D_SKY_SUN_ALTITUDE_SCALE;
	g_alpha_sun = LH3D_SKY_ALPHA_MAX;
	if (time < LH3D_SKY_SUNRISE_TIME)
	{
		if (time < LH3D_SKY_SUN_FADE_START)
		{
			g_alpha_sun = 0.0f;
		}
		else
		{
			g_alpha_sun = (time - LH3D_SKY_SUN_FADE_START) * LH3D_SKY_SUN_FADE_SCALE;
		}
	}
	if (time > LH3D_SKY_SUNSET_TIME)
	{
		if (time > LH3D_SKY_SUN_FADE_END)
		{
			g_alpha_sun = 0.0f;
		}
		else
		{
			g_alpha_sun = LH3D_SKY_ALPHA_MAX - (time - LH3D_SKY_SUNSET_TIME) * LH3D_SKY_SUN_FADE_SCALE;
		}
	}
	return altitude * LH3D_SKY_SUN_ALTITUDE_MAX;
}

float LH3DSky::ComputeAlphaEclairagePublique()
{
	static float eveningStart = LH3D_SKY_PUBLIC_LIGHTS_DUSK;
	static float morningEnd = LH3D_SKY_PUBLIC_LIGHTS_DAWN;
	static float fadeDuration = LH3D_SKY_PUBLIC_LIGHTS_FADE;
	float        time = Time2OldSkoolTime(curtime);
	if (time > eveningStart)
	{
		if (time > eveningStart + fadeDuration)
		{
			return LH3D_SKY_ALPHA_MAX;
		}
		return (time - eveningStart) * LH3D_SKY_ALPHA_MAX / fadeDuration;
	}
	if (time > morningEnd)
	{
		return 0.0f;
	}
	if (time < morningEnd - fadeDuration)
	{
		return LH3D_SKY_ALPHA_MAX;
	}
	return (morningEnd - time) * LH3D_SKY_ALPHA_MAX / fadeDuration;
}
