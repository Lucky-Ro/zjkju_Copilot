package hadoop9999.training.exp1;

import org.apache.hadoop.io.WritableComparable;

import java.io.DataInput;
import java.io.DataOutput;
import java.io.IOException;
import java.util.HashSet;
import java.util.Set;

/**
 * 电影数据模型。作为 MapReduce 的 K2 输出键,实现 WritableComparable:
 * compareTo 先按评分 star 降序、同分再按年份 year 降序——这样 MR 洗牌阶段就把
 * 「我的演员」的电影按评分(同分年份近的靠前)排好序,输出取前 5 即为答案。
 */
public class MovieInfo implements WritableComparable<MovieInfo> {

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
	public void write(DataOutput out) throws IOException {
		out.writeUTF(this.title);
		out.writeInt(this.year);
		out.writeUTF(this.type);
		out.writeFloat(this.star);
		out.writeUTF(this.director);
		out.writeUTF(this.actor);
		out.writeUTF(this.time);
		out.writeUTF(this.film_page);

	}

	@Override
	public void readFields(DataInput in) throws IOException {
		this.title=in.readUTF();
		this.year=in.readInt();
		this.type=in.readUTF();
		this.star=in.readFloat();
		this.director=in.readUTF();
		this.actor=in.readUTF();
		this.time=in.readUTF();
		this.film_page=in.readUTF();
	}

	@Override
	public int compareTo(MovieInfo o) {
		if(o==null){
			return -1;
		}else{
			if(star>o.star){
				return -1;
			}else if(star==o.star){
				return year>o.year?-1:1;
			}else{
				return 1;
			}
		}
	}

	@Override
	public String toString(){
		return title+"（"+year+"）,"+"评分："+star;
	}
}
