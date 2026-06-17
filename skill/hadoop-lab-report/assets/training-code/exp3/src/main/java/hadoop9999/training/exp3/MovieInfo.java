package hadoop9999.training.exp3;

import java.util.HashSet;
import java.util.Set;

/** 电影数据模型(纯 POJO,供 fastjson 反序列化 Film.json 的每行 JSON)。 */
public class MovieInfo {

	private String title;
	private int year;
	private String type;
	private float star;
	private String director;
	private String actor;
	private String time;
	private String film_page;
	private String doubanId;
	public Set<String> getActorSet(){
		Set<String> set=new HashSet<>();
		if(actor!=null){
			String[] as=actor.split(",");
			String trimActorName=null;
			for(String a:as){
				trimActorName=a.trim();
				if(!"".equals(trimActorName)){
					set.add(trimActorName);
				}
			}
		}
		return set;
	}
	public String getTitle() {
		return title;
	}
	public void setTitle(String title) {
		this.title = title;
	}
	public int getYear() {
		return year;
	}
	public void setYear(int year) {
		this.year = year;
	}
	public String getType() {
		return type;
	}
	public void setType(String type) {
		this.type = type;
	}
	public float getStar() {
		return star;
	}
	public void setStar(float star) {
		this.star = star;
	}
	public String getDirector() {
		return director;
	}
	public void setDirector(String director) {
		this.director = director;
	}
	public String getActor() {
		return actor;
	}
	public void setActor(String actor) {
		this.actor = actor;
	}
	public String getFilm_page() {
		return film_page;
	}
	public void setFilm_page(String film_page) {
		this.film_page = film_page;
	}
	public String getTime() {
		return time;
	}
	public void setTime(String time) {
		this.time = time;
	}

	public String getDoubanId() {
		if(film_page!=null){
			doubanId=film_page.substring(33,film_page.length()-1);
		}
		return doubanId;
	}


	@Override
	public String toString(){
		return title+"（"+year+"）,"+"评分："+star;
	}
}
