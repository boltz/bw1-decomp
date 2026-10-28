#include "LH3DSky.h"

#include <math.h>
#include <string.h>

#include <re_common.h>

#include "LH3DAtmos.h"
#include "LH3DColor.h"
#include "LH3DIsland.h"
#include "LH3DLevelOfDetail.h"
#include "LH3DMaterial.h"
#include "LH3DMem.h"
#include "LH3DMesh.h"
#include "LH3DObject.h"
#include "LH3DPrimitive.h"
#include "LH3DRender.h"
#include "LH3DSubMesh.h"
#include "LH3DTech.h"
#include "LH3DTexture.h"
#include "LHMatrix.h"
#include "LHPoint.h"

#include <Lionhead/LHFile/ver3.0/LHOSFile.h>

int         LH3DSky::g_b_we_are_inside_citadel;
float       LH3DSky::g_alpha_sun = 255.0f;
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
LH3DColor   LH3DSky::lightcols[8];
void*       LH3DSky::bitmaps[3][3];
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

LH3DTexture*  sky_texture[3];
LH3DMaterial* sky_material[3];

bool32_t g_jc_caca_first_init_sky = true;
int      g_fade;
bool     moonflip;

static char g_sky_texture_name[0x100];

// BW1W120 00822190 BW1M119 010a4860 (LHCombined Release)
void* LoadTextureCitadel(char* name, unsigned char* data);

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
	bool folded = false;
	if (time > HOURS_PER_HALF_DAY)
	{
		time = HOURS_PER_DAY - time;
		folded = true;
	}

	int   index;
	float fraction;
	if (time < from_night)
	{
		index = 0;
		fraction = time / from_night;
	}
	else if (time < from_dusk_start)
	{
		index = 1;
		fraction = (time - from_night) / (from_dusk_start - from_night);
	}
	else if (time < from_dusk_end)
	{
		index = 2;
		fraction = (time - from_dusk_start) / (from_dusk_end - from_dusk_start);
	}
	else if (time < from_day)
	{
		index = 3;
		fraction = (time - from_dusk_end) / (from_day - from_dusk_end);
	}
	else
	{
		index = 4;
		fraction = (time - from_day) / (HOURS_PER_HALF_DAY - from_day);
	}

	float result;
	switch (index)
	{
	case 0:
		result = fraction * to_night;
		break;
	case 1:
		result = to_night + fraction * (to_dusk_start - to_night);
		break;
	case 2:
		result = to_dusk_start + fraction * (to_dusk_end - to_dusk_start);
		break;
	case 3:
		result = to_dusk_end + fraction * (to_day - to_dusk_end);
		break;
	case 4:
		result = to_day + fraction * (HOURS_PER_HALF_DAY - to_day);
		break;
	}

	if (folded)
	{
		result = HOURS_PER_DAY - result;
	}
	return result;
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
	float sky_type = SKY_TYPE_DAY;
	if (time > HOURS_PER_HALF_DAY)
	{
		time = HOURS_PER_DAY - time;
	}
	if (time < NIGHT_FULL_TIME)
	{
		sky_type = SKY_TYPE_NIGHT;
	}
	else if (time < DUSK_START_TIME)
	{
		sky_type = SKY_TYPE_NIGHT - (time - NIGHT_FULL_TIME) / (DUSK_START_TIME - NIGHT_FULL_TIME);
	}
	else if (time < DUSK_END_TIME)
	{
		sky_type = SKY_TYPE_DUSK;
	}
	else if (time < DAY_FULL_TIME)
	{
		sky_type = SKY_TYPE_DUSK - (time - DUSK_END_TIME) / (DAY_FULL_TIME - DUSK_END_TIME);
	}
	return sky_type;
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
		time += HOURS_PER_DAY;
	}
	while (time >= HOURS_PER_DAY)
	{
		time -= HOURS_PER_DAY;
	}
	curtime = time;
	newst = Time2SkyType(time);
}

void LH3DSky::Update()
{
	CalculateColours();
	int height = LH3DTexture::g_b_use_low_res ? SKY_TEXTURE_HEIGHT_LOW : SKY_TEXTURE_HEIGHT;
	if (cury >= height)
	{
		if (fabs(newst - curst) > SKY_TYPE_CHANGE_THRESHOLD)
		{
			curst = newst;
			cury = 0;
		}
		if (cury >= height)
		{
			return;
		}
	}
	CalculateTextures(curst, cury, SKY_TEXTURE_UPDATE_LINES);
	cury += SKY_TEXTURE_UPDATE_LINES;
}

static bool IsInsideCitadel()
{
	if (LH3DLevelOfDetail::g_b_inside_citadel != 0 && !LH3DTexture::g_b_use_low_res)
	{
		return true;
	}
	return false;
}

void LH3DSky::Draw()
{
	LHPoint moon_position = LH3DAtmos::moonpos;

	int moon_fog = (int)(moon_position.y * LH3D_SKY_MOON_FOG_SCALE - LH3D_SKY_MOON_FOG_OFFSET);
	if (moon_fog > LH3D_SKY_MOON_FOG_MAX)
	{
		moon_fog = LH3D_SKY_MOON_FOG_MAX;
	}
	if (overcast > 0.0f && LH3DIsland::g_b_use_fog)
	{
		moon_fog = (int)((float)moon_fog / (overcast * LH3D_SKY_FOG_SCALE + 1.0f));
	}

	uint32_t specular = 0;
	if (moon_fog > 0)
	{
		moon_position.x += LH3DTech::g_camera.pos.x;
		moon_position.y += LH3DTech::g_camera.pos.y;
		moon_position.z += LH3DTech::g_camera.pos.z;
		moonobj->SetNeedClipping(1);
	}

	int fog_alpha;
	int sky_index;
	int sky_index_second;
	if (evil < 0.0f)
	{
		evil = 0.0f;
		fog_alpha = (int)(evil * 255.0f);
		sky_index = 0;
		sky_index_second = 1;
	}
	else
	{
		if (evil > 2.0f)
		{
			evil = 2.0f;
		}
		fog_alpha = (int)((evil - 1.0f) * 255.0f);
		sky_index = 1;
		sky_index_second = 2;
	}

	int inv_fog = 0xff - fog_alpha;

	LH3DRender::SetRenderState(D3DRENDERSTATE_ZFUNC, D3DCMP_ALWAYS);

	int      fog = (int)(overcast * 255.0f);
	uint32_t top_colour = 0xffffffff;
	if (!IsInsideCitadel())
	{
		float sky_scale = (2.0f - newst) * LH3D_SKY_TOP_SCALE;
		float red_scale = sky_scale + sky_scale + LH3D_SKY_TOP_OFFSET;
		float green_scale = sky_scale * LH3D_SKY_TOP_GREEN_SCALE + LH3D_SKY_TOP_OFFSET;
		float blue_scale = sky_scale * LH3D_SKY_TOP_BLUE_SCALE + LH3D_SKY_TOP_OFFSET;
		if (red_scale > 1.0f)
		{
			red_scale = 1.0f;
		}
		if (green_scale > 1.0f)
		{
			green_scale = 1.0f;
		}
		if (blue_scale > 1.0f)
		{
			blue_scale = 1.0f;
		}

		LH3DColor colour = topcol;
		colour.r = (uint8_t)((float)colour.r * red_scale);
		colour.g = (uint8_t)((float)colour.g * green_scale);
		colour.b = (uint8_t)((float)colour.b * blue_scale);
		colour.a = 0xff;
		top_colour = colour.GetColor();
	}

	uint32_t fog_colour =
		((uint32_t)(uint8_t)fog_red << 16) | ((uint32_t)(uint8_t)fog_green << 8) | (uint8_t)fog_blue | 0xff000000;

	if (LH3DIsland::g_b_use_fog)
	{
		top_colour = LH3D_BLEND_COLOR(top_colour, fog_colour, fog);
		specular = LH3D_BLEND_COLOR(0, fog_colour, fog);
	}

	if (LH3DAtmos::alignment & 1)
	{
		int fade = (LH3DAtmos::fade * LH3DAtmos::fade) / LH3D_ATMOS_ALIGNMENT_FADE;
		top_colour = LH3D_BLEND_COLOR(0, top_colour, 0xff - fade);
		specular = LH3D_BLEND_COLOR(0, specular, 0xff - fade);
	}

	if (g_fade != 0)
	{
		top_colour = LH3D_BLEND_COLOR(top_colour, 0xffffffff, g_fade);
		specular = LH3D_BLEND_COLOR(specular, 0xffffffff, g_fade / 2);
	}

	if (inv_fog < 1)
	{
		DrawSky(sky_index_second, 0xff, top_colour, specular);
	}
	else
	{
		DrawSky(sky_index, 0xff, top_colour, specular);
		if (fog_alpha > 0)
		{
			DrawSky(sky_index_second, fog_alpha, top_colour, specular);
		}
	}

	LH3DRender::SetRenderState(D3DRENDERSTATE_ZFUNC, D3DCMP_LESSEQUAL);

	DrawSun();

	if (moon_fog > 0)
	{
		LH3DColor moon_colour = lightcols[5];
		moon_colour.a = (uint8_t)moon_fog;
		moonflip = false;
		LHMatrix moon_matrix;
		LHMatrix sun_matrix;
		CalcMoonMat(moon_position, moon_matrix, sun_matrix);
		DrawMoonPost(moon_colour, moon_matrix, sun_matrix);
		moon_position.y = -moon_position.y;
		moonflip = true;
		CalcMoonMat(moon_position, moon_matrix, sun_matrix);
		DrawMoonPost(moon_colour, moon_matrix, sun_matrix);
	}
}

void LH3DSky::Init(float time, float overcast)
{
	SetDayNightTimes(LH3D_SKY_DEFAULT_NIGHT, LH3D_SKY_DEFAULT_DUSK, LH3D_SKY_DEFAULT_DUSK_END, LH3D_SKY_DEFAULT_DAY);
	g_jc_caca_first_init_sky = true;
	moonsize = LH3D_SKY_MOON_SIZE_DEFAULT;
	moonsize = LH3D_SKY_MOON_SIZE;
	memset(bitmaps, 0, sizeof(bitmaps));

	int count = IsInsideCitadel() ? SKY_DETAIL_COUNT : SKY_DETAIL_COUNT_DAY;
	for (int detail = 0; detail < count; detail++)
	{
		for (int sky_type = 0; sky_type < SKY_TYPE_COUNT; sky_type++)
		{
			strcpy(g_sky_texture_name, "Data\\WeatherSystem\\sky_");
			if (sky_type == 0)
			{
				strcat(g_sky_texture_name, "good");
			}
			else if (sky_type == 1)
			{
				strcat(g_sky_texture_name, "ntrl");
			}
			else
			{
				strcat(g_sky_texture_name, "evil");
			}
			if (detail == 0)
			{
				strcat(g_sky_texture_name, "_day.555");
			}
			else if (detail == 1)
			{
				strcat(g_sky_texture_name, "_dusk.555");
			}
			else
			{
				strcat(g_sky_texture_name, "_night.555");
			}
			bitmaps[detail][sky_type] = LoadTextureCitadel(g_sky_texture_name, NULL);
		}
		if (bitmaps[detail][0] == NULL)
		{
			bitmaps[detail][0] = bitmaps[detail][1];
		}
		if (bitmaps[detail][2] == NULL)
		{
			bitmaps[detail][2] = bitmaps[detail][1];
		}
	}

	int i;
	for (i = 0; i < SKY_DETAIL_COUNT; i++)
	{
		TextureFormat format;
		sky_texture[i] = LH3DTexture::Create(NULL, LH3D_SKY_TEXTURE_SIZE, 0, &format);
		sky_material[i] = LH3DRender::CreateMaterial(LH3DMaterial::LH3D_MATERIAL_RENDER_MODE_TEXTURED, sky_texture[i]);
	}

	int height = LH3DTexture::g_b_use_low_res ? SKY_TEXTURE_HEIGHT_LOW : SKY_TEXTURE_HEIGHT;
	CalculateTextures(Time2SkyType(overcast), 0, height);
	cury = height;
	newst = 0.0f;
	evil = time * LH3D_SKY_EVIL_SCALE;
	curst = 0.0f;
	SetTime(overcast);
	LH3DSky::overcast = 0.0f;
	CalculateColours();

	uint32_t file_length;
	LHFileLength("data\\weathersystem\\sky.l3d", &file_length);
	void* data = LH3DMem::Alloc(file_length);
	LHLoadData("data\\weathersystem\\sky.l3d", data, file_length, NULL);
	skymesh = LH3DMesh::Create(data, false);
	LH3DMem::Free(data);

	sky = LH3DObject::Create(LH3DObject::STATIC);
	sky->SetMesh(skymesh, NULL, NULL);
	sky->SetDynamicLighting(false);
	sky->SetPosition(LHPoint(LH3D_SKY_POSITION, 0.0f, LH3D_SKY_POSITION), 0.0f, LH3D_SKY_SCALE);

	int j;
	moon = LH3DMesh::CreateFromHD("Data\\WeatherSystem\\moon.l3d", 1);
	for (i = 0; i < moon->SubmeshCount; i++)
	{
		LH3DSubMesh* submesh = moon->submeshes[i];
		for (j = 0; j < submesh->NumPrimitives; j++)
		{
			LH3DPrimitive* primitive = submesh->primitives_[j];
			primitive->Material.texture = g_weather_texture;
		}
	}

	sun = LH3DMesh::CreateFromHD("Data\\WeatherSystem\\sun.l3d", 1);
	for (i = 0; i < sun->SubmeshCount; i++)
	{
		LH3DSubMesh* submesh = sun->submeshes[i];
		for (j = 0; j < submesh->NumPrimitives; j++)
		{
			LH3DPrimitive* primitive = submesh->primitives_[j];
			primitive->Material.render_mode = LH3DMaterial::LH3D_MATERIAL_RENDER_MODE_ALPHA_TEXTURED_ALPHA_ADDITIF_NZ;
			primitive->Material.Flags = primitive->Material.Flags | LH3DMaterial::FLAG_DOUBLE_SIDED;
			primitive->Material.texture = g_sun_texture;
		}
	}

	moonobj = LH3DObject::Create(LH3DObject::STATIC);
	moonobj->SetMesh(moon, NULL, NULL);
	moonobj->SetDynamicLighting(false);

	sunobj = LH3DObject::Create(LH3DObject::STATIC);
	sunobj->SetMesh(sun, NULL, NULL);
}

void LH3DSky::DrawMoonPost(LH3DColor& colour, LHMatrix& matrix, LHMatrix& moon_matrix)
{
	LH3DAtmos::v_idx[0][0] = 0;
	LH3DAtmos::v_idx[0][1] = 1;
	LH3DAtmos::v_idx[0][2] = 3;
	LH3DAtmos::v_idx[0][3] = 3;
	LH3DAtmos::v_idx[0][4] = 2;
	LH3DAtmos::v_idx[0][5] = 0;

	LH3DAtmos::v_uv[0][0] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[0][1] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[0][2] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[0][3] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[0][4] = LH3D_SKY_MOON_UV_MIN;
	LH3DAtmos::v_uv[0][5] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[0][6] = LH3D_SKY_MOON_UV_MAX;
	LH3DAtmos::v_uv[0][7] = LH3D_SKY_MOON_UV_MAX;

	LH3DColor moon_colour = colour;
	moon_colour.r = (uint8_t)((int)moon_colour.r / LH3D_SKY_MOON_RED_DIVISOR);
	moon_colour.g = (uint8_t)((int)moon_colour.g / LH3D_SKY_MOON_GREEN_DIVISOR);
	moon_colour.b >>= LH3D_SKY_MOON_BLUE_SHIFT;

	LH3DAtmos::v_col[0][0] = moon_colour;
	LH3DAtmos::v_col[0][1] = moon_colour;
	LH3DAtmos::v_col[0][2] = moon_colour;
	LH3DAtmos::v_col[0][3] = moon_colour;

	LH3DAtmos::v_pnt[0][0].x = matrix.m[9] - (matrix.m[3] + matrix.m[0]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][0].y = matrix.m[10] - (matrix.m[4] + matrix.m[1]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][0].z = matrix.m[11] - (matrix.m[5] + matrix.m[2]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][1].x = matrix.m[9] + (matrix.m[0] - matrix.m[3]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][1].y = matrix.m[10] + (matrix.m[1] - matrix.m[4]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][1].z = matrix.m[11] + (matrix.m[2] - matrix.m[5]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][2].x = matrix.m[9] + (matrix.m[3] - matrix.m[0]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][2].y = matrix.m[10] + (matrix.m[4] - matrix.m[1]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][2].z = matrix.m[11] + (matrix.m[5] - matrix.m[2]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][3].x = matrix.m[9] + (matrix.m[3] + matrix.m[0]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][3].y = matrix.m[10] + (matrix.m[4] + matrix.m[1]) * LH3D_SKY_MOON_QUAD_SIZE;
	LH3DAtmos::v_pnt[0][3].z = matrix.m[11] + (matrix.m[5] + matrix.m[2]) * LH3D_SKY_MOON_QUAD_SIZE;

	LH3DTech::Draw3DWorldTriangle(LH3D_SKY_MOON_VERTEX_COUNT, LH3DAtmos::v_pnt[0], LH3DAtmos::v_col[0],
	                              LH3DAtmos::v_uv[0], LH3D_SKY_MOON_TRIANGLE_COUNT, LH3DAtmos::v_idx[0],
	                              LH3DAtmos::AdditiveMaterial, 0);

	moonobj->matrix = moon_matrix;
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

float LH3DSky::GetSunVisibility()
{
	static float sampleOffset = LH3D_SKY_SUN_SAMPLE_OFFSET;
	LHPoint      samples[] = {
		LHPoint(0.0f, 0.0f, 0.0f),                   //
		LHPoint(-sampleOffset, -sampleOffset, 0.0f), //
		LHPoint(-sampleOffset, sampleOffset, 0.0f),  //
		LHPoint(sampleOffset, -sampleOffset, 0.0f),  //
		LHPoint(sampleOffset, sampleOffset, 0.0f),   //
	};
	LHPoint direction = g_sun_pos;
	direction -= LH3DTech::g_camera.pos;
	direction.SetSize(LH3DTech::g_info_transform.NearClip);

	HRESULT        lockResult = S_FALSE;
	bool32_t       readDepth = g_b_zbuffer_16b;
	DDSURFACEDESC2 surface;
	if (LH3DLevelOfDetail::g_detail_idx != LH3DLevelOfDetail::DETAIL_PRESET_3 &&
	    LH3DLevelOfDetail::g_detail_idx != LH3DLevelOfDetail::DETAIL_PRESET_4 &&
	    LH3DLevelOfDetail::g_detail_idx != LH3DLevelOfDetail::DETAIL_PRESET_6)
	{
		readDepth = false;
	}
	if (readDepth)
	{
		memset(&surface, 0, sizeof(surface));
		surface.dwSize = sizeof(surface);
		lockResult =
			LH3DRender::ZBufferSurface->Lock(NULL, &surface, DDLOCK_WAIT | DDLOCK_READONLY | DDLOCK_NOSYSLOCK, NULL);
	}

	float occludedSamples = 0.0f;
	for (int i = 0; i < ARRAY_SIZE(samples); ++i)
	{
		samples[i] += g_sun_pos;
		samples[i] += direction;
		if (samples[i].y < LH3D_SKY_SUN_MIN_HEIGHT)
		{
			samples[i].y = LH3D_SKY_SUN_MIN_HEIGHT;
		}
		float    hitX, hitZ;
		bool32_t occluded = LH3DIsland::RayCast(LH3DTech::g_camera.pos, samples[i], &hitX, &hitZ);
		if (!occluded && lockResult == DD_OK && readDepth)
		{
			int x, y;
			if (LH3DTech::ProjectPoint(&samples[i], &x, &y) == LH3DTech::PROJECT_POINT_INSIDE_VIEWPORT)
			{
				if (x < 0)
				{
					x = 0;
				}
				if (y < 0)
				{
					y = 0;
				}
				if (x >= surface.dwWidth)
				{
					x = surface.dwWidth - 1;
				}
				if (y >= surface.dwHeight)
				{
					y = surface.dwHeight - 1;
				}
				uint16_t* depth = (uint16_t*)surface.lpSurface;
				if (depth[x + surface.lPitch * y / (int)sizeof(*depth)] < LH3D_SKY_SUN_DEPTH_THRESHOLD)
				{
					occluded = true;
				}
			}
		}
		occludedSamples += (occluded != false);
	}
	if (readDepth && lockResult == DD_OK)
	{
		LH3DRender::ZBufferSurface->Unlock(NULL);
	}
	return (1.0f - occludedSamples * LH3D_SKY_SUN_SAMPLE_WEIGHT) * LH3D_SKY_ALPHA_MAX;
}
